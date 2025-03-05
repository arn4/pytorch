// in this file, we will implement the stuff in library_stable.h,
// and we are allowed to call unstable stuff from pytorch!

#include <ATen/ATen.h>
#include <ATen/core/Tensor.h>
#include <ATen/DeviceGuard.h>
#include <ATen/core/boxing/KernelFunction.h>
#include <ATen/core/TensorAccessor.h>
#include <ATen/core/ivalue.h>
#include <ATen/core/stack.h>
#include <ATen/cuda/CUDAContext.h>
#include <c10/cuda/CUDAGuard.h>
#include <c10/util/bit_cast.h>
#include <torch/csrc/inductor/aoti_runtime/utils.h>
#include <torch/csrc/inductor/aoti_torch/utils.h>
#include <torch/library.h>
#include <torch/library_stable.h>


class StableLibrary::TorchLibraryOpaque {
  public:
    // TODO: support other Kinds lol, you'll need to translate between StableLibrary::Kind and Library::Kind
    TorchLibraryOpaque(StableLibrary::Kind kind, std::string ns, std::optional<c10::DispatchKey> k, const char* file, uint32_t line)
        : library_(torch::Library::Kind::IMPL, std::move(ns), k, file, line) {}

    TorchLibraryOpaque(const TorchLibraryOpaque&) = delete;
    TorchLibraryOpaque& operator=(const TorchLibraryOpaque&) = delete;
    TorchLibraryOpaque(TorchLibraryOpaque&&) = default;
    TorchLibraryOpaque& operator=(TorchLibraryOpaque&&) = default;
    ~TorchLibraryOpaque() = default;

    void impl(const char* name, torch::CppFunction fn) {
      library_.impl(name, std::move(fn));
    }
  private:
      torch::Library library_; // Actual Library object
};


using RAIIATH = torch::aot_inductor::RAIIAtenTensorHandle;

template <typename T>
uint64_t from(T val) {
  static_assert(sizeof(T) <= sizeof(uint64_t), "StableLibrary stack does not support parameter types larger than 64 bits.");
  return *reinterpret_cast<uint64_t*>(&val);
}

template <typename T>
T to(uint64_t val) {
  return *reinterpret_cast<T*>(&val);
}

class StableIValueConverter: public c10::OperatorKernel {
  public:
    StableIValueConverter(void (*fn)(uint64_t*, int64_t, int64_t)) : fn_(fn) {}

    void operator()(const c10::OperatorHandle& op, c10::DispatchKeySet keyset, torch::jit::Stack* stack) {
      const auto& schema = op.schema();
      const auto num_returns = schema.returns().size();
      const auto num_arguments = schema.arguments().size();
      // to make this faster, you can make this a C array on the stack --> though this may cause a stackoverflow
      uint64_t *ministack = (uint64_t*)malloc((num_arguments + num_returns) * sizeof(uint64_t));
      // std::unique_ptr<void *[]> ministack = std::make_unique<void*[]>(num_arguments + num_returns);

      for (size_t idx = 0; idx < num_arguments; idx++) {  // rbarnes will prefer a c10::irange instead of this loop!
        const c10::IValue& arg = torch::jit::peek(stack, idx, num_arguments);
        if (arg.isInt()) {
          TORCH_WARN("dealt with an Int");
          ministack[idx] = from(arg.toInt());
        } else if (arg.isDouble()) {
          TORCH_WARN("dealt with a double");
          ministack[idx] = from(arg.toDouble());
        } else if (arg.isBool()) {
          TORCH_WARN("dealt with a bool");
          ministack[idx] = from(arg.toBool());
        } else if (arg.isNone()) {
          TORCH_WARN("dealt with a None");
          ministack[idx] = from(nullptr);
        } else if (arg.isTensor()) {
          TORCH_WARN("dealt with a Tensor");
          AtenTensorHandle ath = torch::aot_inductor::new_tensor_handle(std::move(const_cast<at::Tensor&>(arg.toTensor())));
          ministack[idx] = from(ath);
        } else {
          TORCH_CHECK(false, "Other types of IValues not yet handled!");
        }
      }

      // second function is going to take a stack of uint64_ts, cast them to our
      // schema values, and run the function and modify the uint64_t stack
      fn_(ministack, num_arguments, num_returns);

      // now pop all inputs on stack. if we pop earlier, Tensors would go out of scope
      // before calling the function
      torch::jit::drop(stack, num_arguments);

      // read the output from the end of the stack and wrap that back into
      // IValue from void*?
      for (size_t idx = 0; idx < num_returns; idx++) {
        const c10::TypePtr& ret_type = schema.returns()[idx].type();
        if (*ret_type == *c10::getTypePtr<at::Tensor>()) {
          auto ret_raiiath = RAIIATH(to<AtenTensorHandle>(ministack[num_arguments + idx]));
          at::Tensor out = *torch::aot_inductor::tensor_handle_to_tensor_pointer(ret_raiiath.get());
          torch::jit::push(stack, c10::IValue(out));
        } else {
          TORCH_CHECK(false, "Only Tensor return types are currently supported!");
        }
      }

      free(ministack);
    }

  private:
    void (*fn_)(uint64_t*, int64_t, int64_t);
};


StableLibrary::StableLibrary(StableLibrary::Kind kind, std::string ns, std::optional<c10::DispatchKey> k, const char* file, uint32_t line)
 : lib_(new TorchLibraryOpaque(StableLibrary::Kind::IMPL, std::move(ns), k, file, line)) {}


StableLibrary& StableLibrary::impl(const char* name, void (*fn)(uint64_t*, int64_t, int64_t)) {
  this->lib_->impl(name, torch::CppFunction::makeFromBoxedFunctor(std::move(std::make_unique<StableIValueConverter>(fn))));
  return *this;
}
