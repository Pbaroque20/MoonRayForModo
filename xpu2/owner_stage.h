#pragma once
#include <stdexcept>
namespace xpu2 {
// Owner-thread FIFO. Entries are leases into storage kept alive by the caller.
// Native publication order remains FIFO; no spin or wait is permitted here.
class OwnerStage {
    unsigned capacity_,head_=0,size_=0;
public:
    explicit OwnerStage(unsigned capacity):capacity_(capacity){if(!capacity || capacity>4)throw std::logic_error("Invalid owner stage capacity");}
    unsigned size()const{return size_;}
    bool full()const{return size_==capacity_;}
    unsigned tail()const{if(full())throw std::logic_error("Owner stage full");return (head_+size_)%capacity_;}
    unsigned front()const{if(!size_)throw std::logic_error("Owner stage empty");return head_;}
    void push(){if(full())throw std::logic_error("Owner stage overbooked");++size_;}
    void pop(){if(!size_)throw std::logic_error("Owner stage underflow");head_=(head_+1)%capacity_;--size_;}
};
}
