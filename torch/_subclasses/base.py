# mypy: ignore-errors

import importlib
from typing import Callable, List, Optional

import torch
import torch.utils._pytree as pytree
from torch.utils._python_dispatch import return_and_correct_aliasing


def gen_tensor_flatten_fn(inner_tensors: List[str], get_meta_fn: Optional[Callable]):
    if get_meta_fn is not None:

        def __tensor_flatten__(self):
            return inner_tensors, get_meta_fn(self)

        return __tensor_flatten__

    def __tensor_flatten__(self):
        return inner_tensors, None

    return __tensor_flatten__


def gen_tensor_unflatten_fn(
    module_name: str,
    class_name: str,
    inner_tensors_attrs: List[str],
    meta_init_kwargs_fn: Optional[Callable],
):
    if meta_init_kwargs_fn:

        def __tensor_unflatten__(inner_tensors, meta, outer_size, outer_stride):
            kwargs_tensors = {a: inner_tensors[a] for a in inner_tensors_attrs}
            module = importlib.import_module(module_name)
            clz = getattr(module, class_name)
            kwargs = kwargs_tensors
            kwargs.update(meta_init_kwargs_fn(meta))

            return clz(outer_size=outer_size, outer_stride=outer_stride, **kwargs)

        return __tensor_unflatten__

    def __tensor_unflatten__(inner_tensors, meta, outer_size, outer_stride):
        kwargs_tensors = {a: inner_tensors[a] for a in inner_tensors_attrs}
        module = importlib.import_module(module_name)
        clz = getattr(module, class_name)
        kwargs = kwargs_tensors

        return clz(outer_size=outer_size, outer_stride=outer_stride, **kwargs)

    return __tensor_unflatten__


def gen_torch_function(
    torch_fn_pro: Optional[Callable], torch_fn_epi: Optional[Callable]
):
    if torch_fn_pro is None:

        def fn(cls, func, types, args=(), kwargs=None):
            if kwargs is None:
                kwargs = {}
            with torch._C.DisableTorchFunctionSubclass():
                return torch_fn_epi.__wrapped__(
                    cls, func, types, args, kwargs, func(*args, **kwargs)
                )

        return fn
    elif torch_fn_epi is None:

        def fn(cls, func, types, args=(), kwargs=None):
            if kwargs is None:
                kwargs = {}
            if ret := torch_fn_pro.__wrapped__(cls, func, types, args, kwargs):
                return ret
            with torch._C.DisableTorchFunctionSubclass():
                return func(*args, **kwargs)

        return fn

    def fn(cls, func, types, args=(), kwargs=None):
        if kwargs is None:
            kwargs = {}
        if ret := torch_fn_pro.__wrapped__(cls, func, types, args, kwargs):
            return ret
        with torch._C.DisableTorchFunctionSubclass():
            return torch_fn_epi.__wrapped__(
                cls, func, types, args, kwargs, func(*args, **kwargs)
            )

    return fn


def gen_repr(qualname, inner_tensors_attrs):
    def fn(self):
        r = ", ".join([f"{a}:{repr(getattr(self, a))}" for a in inner_tensors_attrs])
        return f"{qualname}({r})"

    return fn


class BaseTensorSubclassMeta(torch._C._TensorMeta):
    def __new__(meta, name, bases, attrs):
        if "INNER_TENSORS" in attrs:
            inner_tensors = attrs["INNER_TENSORS"]
            if "__tensor_flatten__" not in attrs:
                attrs["__tensor_flatten__"] = gen_tensor_flatten_fn(
                    inner_tensors, attrs.get("get_meta", None)
                )

            if "__tensor_unflatten__" not in attrs:
                module_name = attrs["__module__"]
                attrs["__tensor_unflatten__"] = staticmethod(
                    gen_tensor_unflatten_fn(
                        module_name,
                        attrs["__qualname__"],
                        inner_tensors,
                        attrs.get("meta_init_kwargs", None),
                    )
                )

            if "__slots__" not in attrs:
                attrs["__slots__"] = inner_tensors

            if "__repr__" not in attrs:
                attrs["__repr__"] = gen_repr(attrs["__qualname__"], inner_tensors)

        if "__torch_function__" not in attrs and (
            ("torch_function_prologue" in attrs) or ("torch_function_epilogue" in attrs)
        ):
            attrs["__torch_function__"] = classmethod(
                gen_torch_function(
                    attrs.get("torch_function_prologue", None),
                    attrs.get("torch_function_epilogue", None),
                )
            )

        return super().__new__(meta, name, bases, attrs)


def tensor_kwargs_from(t: torch.Tensor, outer_stride=None):
    kwargs = {}
    kwargs["strides"] = outer_stride or t.stride()
    kwargs["storage_offset"] = t.storage_offset()
    kwargs["device"] = t.device
    kwargs["layout"] = t.layout
    kwargs["requires_grad"] = t.requires_grad
    kwargs["dtype"] = t.dtype
    return kwargs


class BaseTensorSubclass(torch.Tensor, metaclass=BaseTensorSubclassMeta):
    # TODO:
    # 1.Check compatibility with dynamo
    # 2.Optional inner tensors
    # 3.Dynamic number of inner tensors
    # 4.Comments
    # 5.Examples

    # def get_meta(self):
    #     return None

    # def meta_init_kwargs(meta):
    #     return {}

    @classmethod
    def _args(cls, args, get_arg_fn):
        return pytree.tree_map_only(cls, get_arg_fn, args)

    @classmethod
    def args_attr(cls, args, attr_name):
        return cls._args(args, lambda x: getattr(x, attr_name))

    @classmethod
    def func_args_kwargs(cls, func, args, kwargs, get_arg_fn):
        args_ = cls.args(args, get_arg_fn)
        kwargs_ = cls.args(kwargs, get_arg_fn)
        return func(*args_, **kwargs_)

    @classmethod
    def func_args_kwargs_attr(cls, func, args, kwargs, attr_name):
        args_ = cls.args_attr(args, attr_name)
        kwargs_ = cls.args_attr(kwargs, attr_name)
        return func(*args_, **kwargs_)

    @classmethod
    def _return(cls, func, args, kwargs, out):
        from torch._higher_order_ops.cond import cond_op

        if func is cond_op:
            return out

        return return_and_correct_aliasing(func, args, kwargs, out)

    # User can override this method to do something before the func is called
    # If return value is not None, it will be returned to the caller of __torch_function__
    # E.g.:
    # @classmethod
    # def torch_function_prologue(cls, func, types, args, kwargs) -> Optional[Any]:
    #     if func is torch.nn.functional.linear:
    #         print("linear")
    #     return None
    #
    # User can override this method to do something after the func is called
    # The return value will be returned to the caller of __torch_function__
    # E.g.:
    # @classmethod
    # def torch_function_epilogue(cls, func, types, args, kwargs, out):
    #     if func is torch.nn.functional.linear:
    #         print("linear")
    #     return out
    #
    # TODO: Comment when this is needed
    # def __coerce_tangent_metadata__(self):
    #     pass
    #
    # TODO: Comment when this is needed
    # def __coerce_same_metadata_as_tangent__(self, flatten_spec, expected_type=None):
    #     pass
