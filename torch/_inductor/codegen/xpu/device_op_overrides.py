from __future__ import annotations

from typing import Optional

from ..common import DeviceOpOverrides, register_device_op_overrides


class XPUDeviceOpOverrides(DeviceOpOverrides):
    def import_get_raw_stream_as(self, name: str) -> str:
        return f"from torch._C import _xpu_getCurrentRawStream as {name}"

    def set_device(self, device_idx: int) -> str:
        return f"torch.xpu.set_device({device_idx})"

    def synchronize(self) -> str:
        return "torch.xpu.synchronize()"

    def device_guard(self, device_idx: int) -> str:
        return f"torch.xpu._DeviceGuard({device_idx})"

    def cpp_device_guard(self) -> str:
        return "at::DeviceGuard"

    def cpp_aoti_device_guard(self) -> str:
        return "AOTIXpuGuard"

    def cpp_stream_guard(self) -> str:
        return "at::xpu::XPUStreamGuard"

    def cpp_aoti_stream_guard(self) -> str:
        return "AOTIXpuStreamGuard"

    def cpp_getStreamFromExternal(self) -> str:
        return "at::xpu::getStreamFromExternal"

    def kernel_header(self) -> str:
        source_codes = """
        #include <torch/csrc/inductor/aoti_runtime/sycl_runtime_wrappers.h>
        """
        return source_codes

    def kernel_driver(self) -> str:
        source_codes = """
            namespace {

            struct Grid {
                Grid(uint32_t x, uint32_t y, uint32_t z)
                  : grid_x(x), grid_y(y), grid_z(z) {}
                uint32_t grid_x;
                uint32_t grid_y;
                uint32_t grid_z;

                bool is_non_zero() {
                    return grid_x > 0 && grid_y > 0 && grid_z > 0;
                }
            };

            }  // anonymous namespace

        """
        return source_codes

    def cpp_stream_type(self) -> str:
        return "sycl::queue*"

    def aoti_get_stream(self) -> str:
        return "aoti_torch_get_current_xpu_stream"

    def cpp_kernel_type(self) -> str:
        return "std::unique_ptr<sycl::kernel>"

    def cpp_device_ptr(self) -> str:
        return "void *"

    def cpp_global_scratch(self, idx: int) -> Optional[tuple[str, str]]:
        return None


register_device_op_overrides("xpu", XPUDeviceOpOverrides())
