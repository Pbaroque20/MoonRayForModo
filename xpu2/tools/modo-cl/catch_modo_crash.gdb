set pagination off
set confirm off
set print thread-events off
handle SIGSEGV stop print pass
handle SIGILL stop print pass
handle SIGTRAP nostop noprint pass
catch signal SIGSEGV
commands
  echo \n==== access violation ====\n
  bt 40
  info registers rip
  thread apply all bt 12
  continue
end
continue
