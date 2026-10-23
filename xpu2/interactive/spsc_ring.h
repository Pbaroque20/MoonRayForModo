// Private bounded same-process queue; not a CPU/GPU mapped-memory protocol.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <type_traits>
#include <utility>
namespace xpu2::interactive {
template<class T,size_t Capacity>class SpscRing {
 static_assert(Capacity>0&&(Capacity&(Capacity-1))==0,"Power-of-two capacity required");
 static_assert(std::is_nothrow_move_assignable<T>::value,"Handoffs cannot throw");
 static_assert(std::atomic<uint64_t>::is_always_lock_free,"Lock-free sequence required");
 std::array<T,Capacity> slots_{};
 alignas(64) std::atomic<uint64_t> write_{0};
 alignas(64) std::atomic<uint64_t> read_{0};
public:
 // Only one producer calls full/tryPush. Failure retains the caller's value.
 bool full()const{return write_.load(std::memory_order_relaxed)-read_.load(std::memory_order_acquire)==Capacity;}
 bool tryPush(T& value)noexcept {
  auto w=write_.load(std::memory_order_relaxed);
  if(w-read_.load(std::memory_order_acquire)==Capacity)return false;
  slots_[w&(Capacity-1)]=std::move(value);write_.store(w+1,std::memory_order_release);return true;
 }
 // Only one consumer calls tryPop. Its destination must not still own resources
 // whose destruction belongs to another thread. A moved slot belongs to it.
 bool tryPop(T& value)noexcept {
  auto n=read_.load(std::memory_order_relaxed);
  if(n==write_.load(std::memory_order_acquire))return false;
  value=std::move(slots_[n&(Capacity-1)]);read_.store(n+1,std::memory_order_release);return true;
 }
};
}
