# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub:
[Report a vulnerability](https://github.com/git-cgallagher/ansible-collection-vmware/security/advisories/new)
(the **Security** tab, then **Report a vulnerability**). Don't open a public issue for a security problem.

You can expect an acknowledgement within a week. This is a one-person project, so fixes are best effort.

## Supported versions

Only the latest release gets fixes.

## Scope

The modules log in to vCenter or ESXi with the credentials your playbook gives them. In scope:

- leaking the password, for example in a result, a warning or an error message;
- the modules acting on a virtual machine or disk other than the one the task names, or deleting a backing
  file when `delete_file` was not set;
- connecting without certificate checks when `validate_certs` was left on.

Vulnerabilities in pyvmomi, vCenter or ESXi themselves belong with Broadcom (VMware).

## A note on test credentials

The tests run against vcsim, which accepts any username and password. Everything that looks like a password in
`tests/` is a placeholder (`Example-not-secret`), and no real vCenter is ever contacted in CI.