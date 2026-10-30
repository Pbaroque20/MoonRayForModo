#include "film_batch_queue.h"
#include <chrono>
#include <iostream>
using namespace filmqueue;
void require(bool v){if(!v)throw std::runtime_error("Queue contract failed");}
int main(){try {
 std::mutex gate;std::condition_variable changed;bool started=false,release=false;
 Queue q([&](const Queue::Batch& batch){
  {std::unique_lock<std::mutex> lock(gate);if(!started){started=true;changed.notify_all();changed.wait(lock,[&]{return release;});}}
  unsigned slots=0;for(auto& j:batch){slots+=j->count;for(unsigned i=0;i<j->count;++i){j->accepted[i]=j->masks[i];j->output[i*64]=j->input[i*192];}}
  require(slots<=BatchSlots);
 });
 std::array<std::shared_ptr<Job>,16> jobs;std::vector<std::thread> producers;
 for(unsigned i=0;i<16;++i){auto j=std::make_shared<Job>();j->count=16;
  for(unsigned s=0;s<16;++s){j->input[s*192]=float(i*100+s);j->masks[s]=int(i+1);}jobs[i]=j;
  producers.emplace_back([&,j]{require(q.submit(j));});
  if(i==0){std::unique_lock<std::mutex> lock(gate);changed.wait(lock,[&]{return started;});}
 }
 auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
 while(q.stats().submitted!=16){if(std::chrono::steady_clock::now()>deadline)std::abort();std::this_thread::yield();}
 auto overflow=std::make_shared<Job>();overflow->count=1;require(!q.submit(overflow));
 std::thread closer([&]{q.close();});
 {std::lock_guard<std::mutex> lock(gate);release=true;changed.notify_all();}
 for(auto& t:producers)t.join();closer.join();q.close();
 auto s=q.stats();require(s.submitted==16&&s.returned==16&&s.batches==3&&s.combined==2&&s.maxSlots==128&&s.maxJobs==8&&s.maxOutstanding==16&&s.duringService==15&&s.exceptions==0);
 for(unsigned i=0;i<16;++i)for(unsigned n=0;n<16;++n)require(jobs[i]->accepted[n]==int(i+1)&&jobs[i]->output[n*64]==float(i*100+n));
 require(!q.submit(overflow));
 Queue failing([](const Queue::Batch& b){for(auto& j:b)j->accepted.fill(255);throw std::runtime_error("injected");});
 auto failed=std::make_shared<Job>();failed->count=1;require(failing.submit(failed));require(failed->accepted[0]==0);require(failing.stats().exceptions==1);
 bool invalid=false;try{failing.submit(failed);}catch(const std::invalid_argument&){invalid=true;}require(invalid);failing.close();
 Queue invalidQueue([](const Queue::Batch&){});auto invalidJob=std::make_shared<Job>();invalidJob->count=17;invalid=false;
 try{invalidQueue.submit(invalidJob);}catch(const std::invalid_argument&){invalid=true;}require(invalid);invalidQueue.close();
 std::cout<<"passed: bounded aggregation, ordered scatter, overflow fallback, close, repeat rejection, exception fallback, invalid count\n";
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
