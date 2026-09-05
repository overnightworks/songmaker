# songmaker-web seccomp profile

`moby-default.json` is the vendored Docker default seccomp profile from
[`moby/profiles`](https://github.com/moby/profiles) `main` commit
`61eaf32614c7c71b60bd8927d3e6a4ffc8ff1f31` (the `default.json` Git blob is
`ea5a494afb8d64898fa0f4f47ae0c4f5ba9cbbc9`, retrieved 2026-09-05).

`songmaker-web.json` differs only by one Bubblewrap setup extension. It allows
the user-namespace and mount syscalls that Docker otherwise gates on
`CAP_SYS_ADMIN`: `unshare`, namespace-flagged `clone`, `mount`,
`umount2`, `pivot_root`, `setns`, `mount_setattr`, `open_tree`, `move_mount`,
and `fsopen`. Docker's JSON policy cannot express “clone with any namespace
flag” as one inverse comparison, so the extension has two rules: the syscall
group and `clone`; ordinary `clone` was already allowed by the default rule.

The profile grants no capability. `songmaker-web` still drops every container
capability and runs with `no-new-privileges`; AppArmor mediates the mount shapes
inside the nested user and mount namespaces. Keep the vendored source and the
derived profile together: `tests/test_seccomp_profile.py` proves that this is
the sole policy extension.
