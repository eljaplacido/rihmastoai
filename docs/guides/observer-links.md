# Share your view: observer links

Let a colleague watch your work for a while, read only: to check what you are doing, or to define a project
together. Open **Share** in the sidebar, or ask Rihma: "share my screen with a colleague for an hour".

## Make a link

1. Choose what to share: **one project**, or **every project** (platform-wide: the page says which).
2. Choose for how long: an hour, a day or a week.
3. Name the guest if you like ("Maria Example"); their comments are signed with that name.
4. Tick **Include confidential projects** only if you mean it. A confidential project is never shown to a guest
   otherwise, and a link for one cannot be made without the tick.
5. Tick **Define the project together** to let the guest suggest answers to the project's open intake
   questions. Each suggestion waits for you: **Confirm as my answer** answers the question, signed by you;
   **Decline** leaves it open.

Press **Make the link**. The address is shown once, with **Copy the link**. Rihmasto sends it nowhere: you pass
it on yourself. Only a hash of the link is kept, with its expiry.

## What your guest sees

Your guest opens the link in a browser on the same computer. From another machine they need an SSH tunnel to the
cockpit (see [Reach it from another machine](../cockpit.md)), and **a tunnel is an SSH login on your host**: with
your account, or any account with a shell, the guest gets far more than read only (your files, your keys, every
project). Never give a guest your own login. Give them a restricted account of their own that can forward the
cockpit's one port and nothing else: in that account's `~/.ssh/authorized_keys`, put the guest's public key behind

```
restrict,port-forwarding,permitopen="127.0.0.1:8787",command="/bin/false" ssh-ed25519 AAAA... guest
```

(use your cockpit's port), and the guest runs `ssh -N -L 8787:127.0.0.1:8787 guest@your-host`. Remove the key
when the link ends. The page shows, read only:

- the projects in the link's scope: each one's overview, plan, decisions waiting, activity and agent channel,
  with secrets masked;
- **Following**: the view you are on and your latest actions. They can pause following; you can pause showing
  where you are (Share, Following). On something outside the link, the page says only that you are elsewhere;
  A pause holds until you resume, whether you paused on Share or asked Rihma ("pause sharing my view"). On a
  project's link, anything without that project (Settings, Share, a view across projects) is "elsewhere" too;
- a comment box: comments are signed with the guest's name and marked as a guest's. A link takes at most ten
  comments (and ten suggestions) in ten minutes; after that the guest is asked to wait a few minutes.

With access enforced (IT's access file or team mode), a link for every project shows only the projects you are
granted, Share lists only the links, comments and projects your grants cover, and a link is revoked by the person
who made it or by someone granted on every project.

A guest never decides, runs, changes a setting, sees a secret or another project. A guest's session sent to any
of the cockpit's own routes is refused.

## Keep track

Share lists each link with its scope, when it expires, when it was last opened and who is watching now; a chip at
the top of every page says who is watching while you share. **Revoke** ends a link and every page opened with
it at once. Every visit, comment and suggestion is in the project's ledger.

From a terminal: `rihmasto share link [project] --hours 1|24|168 --guest NAME --person ... --persona ...`,
`rihmasto share revoke OL-001 --person ... --persona ...` and `rihmasto share list`.
