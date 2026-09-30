# CS 218 Lab 2 report

Name:
SJSU ID:
Fingerprint (from `results/lab2-results.json`, field `fingerprint`):
Your VM route and hypervisor (as you gave it to `--hypervisor`):
Your laptop (make, chip, memory):

Copy this file to `report.md` and answer the questions there. Aim for 900 to 1,300 words
across all five answers; there is no credit for length on its own.

Every question is about your own run. Quote the numbers from your own `results/` folder,
not the examples in the README. When a question asks *why*, the answer is a mechanism from
Sessions 7 to 10 (a trap, a namespace, a cgroup, a page cache, a kernel), not "VMs are
heavier" or "containers are lighter". Those are the conclusions; the marks are for the
reasons.

---

## Question 1: What happens between "start" and "first answer"? (12 points)

From `results/startup-container.json` and `results/startup-vm.json`: give the median time to
first answer for each, and the ratio between them.

Your VM's results split each boot in two: `before_guest_kernel_s` (from the start command
until the guest's kernel began counting its own uptime) and `guest_kernel_uptime_at_ready_s`
(from there until the app answered). Name what happens in each of those two stretches, in
order, as specifically as you can. Then do the same for the container, using
`run_command_s` and `ready_s`: what does Docker do before `docker run` returns, and what
does the container *not* have to do that the VM did?

Finally, your Dockerfile. Give the median `docker stop` time from
`results/startup-container.json`, and explain why it is that size. What would it have been
with a shell-form `CMD`, and why?

## Question 2: Where does the memory go? (12 points)

From `results/memory.json`: for the container and for the VM, give the host-side figure, the
app's own RSS, and the difference.

**The VM.** Account for the difference between what the host holds and what the app uses.
Break it into the pieces you can identify from your own numbers: the guest operating system
(`guest_os_without_app_mb`, and how much of that is page cache), memory the guest considers
free that the host is still holding, and the hypervisor's own process. Which of those pieces
could the hypervisor take back without the guest's help, which only with it, and which
mechanism from Session 8 is the one that asks for it?

**The container.** Your container's difference is small, and may even be negative. Explain
how the host can charge a container for less memory than its own process reports using.
The split in `app_rss_anon_mb` and `app_rss_file_mb` is the clue, and Session 9's image
layers are the rest of the answer. Could two VMs share memory the same way? What would it
take?

## Question 3: Where is the boundary? (12 points)

From `python lab.py probe` (saved in `results/probe-container.json` and
`results/probe-vm.json`):

Choose **five** rows that differ between the container and the VM. For each, say which of
Session 10's four kinds of isolation it shows (what the tenant can *see*, what it can *use*,
what it is allowed to *do*, or what happens when it *breaks*), and name the mechanism that
produces the container's answer: a namespace, a cgroup, the capability set, seccomp, or the
fact of one shared kernel.

Two rows show the **same** value in both: the user namespace and the time namespace. Does
that mean your container and your VM share them? Explain what those numbers are, and what it
does mean for the container that its user namespace is that one.

From `results/crash.json`: give the VM's outage, and how many of the container's health
checks succeeded during it. Explain why the container never noticed. Then the question the
lab deliberately did not let you test: if the same kernel crash happened underneath your
container, what would stop, and on your laptop specifically, what is the kernel that would
have crashed? (The `CPU says hypervisor` row is a hint.)

## Question 4: What does a neighbour cost you? (12 points)

From `results/neighbour.json`: give p50 and p99 for the container and for the VM in each of
the three phases.

Why does p99 move so much more than p50 when the busy loops arrive? Answer in terms of how
the CPU is shared, not in terms of "load".

The limit that restored your latency was set on the **neighbour**, not on you. What is
`--cpus 1` actually doing to the busy loops, in terms of `cpu.max`? In a cloud where the
neighbour is a stranger, who gets to set that knob, and what knob protects *you* without
anybody else's cooperation?

Did the busy loops, running in a container, slow down your VM? Explain the path by which they
did or did not: what do the loops and the VM's virtual CPU actually compete for, on your
laptop? (If you are on the Google Cloud route, explain why the answer is different for you.)

## Question 5: Price it on the auction host (12 points)

Session 7's host: **128 GB of memory, costs $1.00 an hour; 24 tenants, each asks for 8 GB
and pays $0.10 an hour.** WORKED L assumed an idle guest operating system of 100 to 200 MB,
and said plainly that the figure was illustrative, not measured. You have now measured it.

Fill in this table from your own `results/memory.json`. Use GB = 1024 MB, and give each share
as a percentage of 128 GB.

| Boundary per tenant | Your per-tenant figure (MB) | For 24 tenants (GB) | Share of the host |
|---|---|---|---|
| Container: host-side minus RSS (use 0 if yours is negative) | | | |
| VM: guest OS without the app | | | |
| VM: host-side minus RSS | | | |
| WORKED L's assumption, for comparison | 150 | 3.52 | 2.75% |

Then:

1. Which of your two VM rows belongs in WORKED L's column, and why? Say what the other row
   includes that the first does not, and whether a cloud provider would pay for it too.
2. Take the difference between your container row and whichever VM row you chose. How many
   whole 8 GB tenants is that memory, and what does not selling them cost the host per month
   (use 730 hours)? Show the arithmetic.
3. Session 10's verdict table matched the boundary to the neighbour: one team, other teams,
   paying strangers. Using your price, for which of those is the VM boundary worth paying
   for? Take a position; it is the argument that is graded, not the position.

---

## Optional: anything that surprised you (no points, read with interest)

If something did not behave the way you expected, or you went beyond what was asked and
found something, put it here. It does not need to be polished.

## Optional: problems you hit

If a part would not run, or ran differently from what the README describes, say so here. An
accurate account of a failure is worth partial credit on the affected question, and it tells
me something I need to know about the lab.

## AI disclosure

If you used an AI tool, say which one and what you used it for, in one line.
