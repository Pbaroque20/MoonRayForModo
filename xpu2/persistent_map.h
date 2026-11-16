// Immutable AVL map. Copies retain one root; edits copy only a logarithmic path.
#pragma once
#include <algorithm>
#include <functional>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>
namespace xpu2::indexed {
template<class Key,class Value,class Compare=std::less<Key>> class PersistentMap {
    using Item=std::pair<const Key,Value>;
    struct Node;
    using Ptr=std::shared_ptr<const Node>;
    struct Node {
        std::shared_ptr<const Item> item;
        Ptr left,right;
        size_t count;
        int height;
        Node(std::shared_ptr<const Item> value,Ptr a,Ptr b)
          :item(std::move(value)),left(std::move(a)),right(std::move(b)),
           count(1+sizeOf(left)+sizeOf(right)),height(1+std::max(heightOf(left),heightOf(right))){}
    };
    Ptr root_;
    static int heightOf(const Ptr& p){return p?p->height:0;}
    static size_t sizeOf(const Ptr& p){return p?p->count:0;}
    static Ptr node(std::shared_ptr<const Item> item,Ptr left={},Ptr right={}) {
        return std::make_shared<const Node>(std::move(item),std::move(left),std::move(right));
    }
    static Ptr leftRotate(const Ptr& p) {
        auto q=p->right;
        return node(q->item,node(p->item,p->left,q->left),q->right);
    }
    static Ptr rightRotate(const Ptr& p) {
        auto q=p->left;
        return node(q->item,q->left,node(p->item,q->right,p->right));
    }
    static Ptr balanced(Ptr p) {
        if(heightOf(p->left)-heightOf(p->right)>1) {
            if(heightOf(p->left->right)>heightOf(p->left->left))p=node(p->item,leftRotate(p->left),p->right);
            return rightRotate(p);
        }
        if(heightOf(p->right)-heightOf(p->left)>1) {
            if(heightOf(p->right->left)>heightOf(p->right->right))p=node(p->item,p->left,rightRotate(p->right));
            return leftRotate(p);
        }
        return p;
    }
    static Ptr insert(const Ptr& p,const std::shared_ptr<const Item>& item) {
        if(!p)return node(item);
        if(Compare{}(item->first,p->item->first))return balanced(node(p->item,insert(p->left,item),p->right));
        if(Compare{}(p->item->first,item->first))return balanced(node(p->item,p->left,insert(p->right,item)));
        return node(item,p->left,p->right);
    }
    static Ptr remove(const Ptr& p,const Key& key) {
        if(!p)return p;
        if(Compare{}(key,p->item->first)) {
            auto left=remove(p->left,key);return left==p->left?p:balanced(node(p->item,left,p->right));
        }
        if(Compare{}(p->item->first,key)) {
            auto right=remove(p->right,key);return right==p->right?p:balanced(node(p->item,p->left,right));
        }
        if(!p->left)return p->right;
        if(!p->right)return p->left;
        auto successor=p->right;while(successor->left)successor=successor->left;
        return balanced(node(successor->item,p->left,remove(p->right,successor->item->first)));
    }
public:
    class const_iterator {
        friend class PersistentMap;
        Ptr owner;
        std::vector<const Node*> stack;
        void descend(const Node* p){while(p){stack.push_back(p);p=p->left.get();}}
        explicit const_iterator(Ptr root):owner(std::move(root)){descend(owner.get());}
        const_iterator(Ptr root,const Key& key):owner(std::move(root)) {
            auto p=owner.get();
            while(p) {
                if(Compare{}(key,p->item->first)){stack.push_back(p);p=p->left.get();}
                else if(Compare{}(p->item->first,key))p=p->right.get();
                else {stack.push_back(p);return;}
            }
            stack.clear();
        }
    public:
        using iterator_category=std::forward_iterator_tag;
        using value_type=Item;using difference_type=std::ptrdiff_t;
        using pointer=const Item*;using reference=const Item&;
        const_iterator()=default;
        reference operator*() const{return *stack.back()->item;}
        pointer operator->() const{return stack.back()->item.get();}
        const_iterator& operator++(){auto p=stack.back();stack.pop_back();descend(p->right.get());return *this;}
        const_iterator operator++(int){auto before=*this;++*this;return before;}
        bool operator==(const const_iterator& other) const {
            return (stack.empty()?nullptr:stack.back())==(other.stack.empty()?nullptr:other.stack.back());
        }
        bool operator!=(const const_iterator& other) const{return !(*this==other);}
    };
    size_t size() const{return sizeOf(root_);}
    bool empty() const{return !root_;}
    int height() const{return heightOf(root_);}
    const_iterator begin() const{return const_iterator(root_);}
    const_iterator end() const{return {};}
    const_iterator find(const Key& key) const{return const_iterator(root_,key);}
    size_t count(const Key& key) const {
        auto p=root_.get();
        while(p){if(Compare{}(key,p->item->first))p=p->left.get();else if(Compare{}(p->item->first,key))p=p->right.get();else return 1;}
        return 0;
    }
    const Value& at(const Key& key) const {
        auto p=root_.get();
        while(p){if(Compare{}(key,p->item->first))p=p->left.get();else if(Compare{}(p->item->first,key))p=p->right.get();else return p->item->second;}
        throw std::out_of_range("Missing persistent-map key");
    }
    void set(Key key,Value value){root_=insert(root_,std::make_shared<const Item>(std::move(key),std::move(value)));}
    // An empty map given many keys at once, sorted and each once (Compare): a balanced tree made straight from them, a
    // node a key. Set one at a time, a scene's first index of 117,000 keys made two million nodes along their paths.
    void assignSorted(std::vector<std::pair<Key,Value>>&& items) {
        if(root_)throw std::logic_error("assignSorted needs an empty map");
        for(size_t i=1;i<items.size();++i)
            if(!Compare{}(items[i-1].first,items[i].first))throw std::invalid_argument("assignSorted needs sorted, distinct keys");
        std::vector<std::shared_ptr<const Item>> held;held.reserve(items.size());
        for(auto& item:items)held.push_back(std::make_shared<const Item>(std::move(item.first),std::move(item.second)));
        root_=built(held,0,held.size());
    }
private:
    static Ptr built(const std::vector<std::shared_ptr<const Item>>& held,size_t lo,size_t hi) {
        if(lo>=hi)return {};
        const size_t mid=lo+(hi-lo)/2;
        return node(held[mid],built(held,lo,mid),built(held,mid+1,hi));
    }
public:
    size_t erase(const Key& key){auto before=size();root_=remove(root_,key);return before-size();}
};
} // namespace xpu2::indexed
