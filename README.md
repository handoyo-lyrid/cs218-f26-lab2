# CS 218 Lab 2: Isolation and Density

**Due Thursday, October 8, 11:59 PM Pacific. 100 points, in the Labs category.**

Sessions 7 to 10 built the argument from both ends. A virtual machine gives each tenant its
own kernel behind a small door of virtual hardware, and pays for it in memory and start-up
time. A container shares one kernel across every tenant behind a door of several hundred
system calls, and gets its density from exactly that sharing. On September 22 we ran six
probes inside a container and watched it leak what it was never told to hide.

This lab puts numbers on that argument, on your own machine. You will run one program,
unchanged, in a container and in a virtual machine, and measure what each costs to start,
what each costs in memory, and where each one's isolation boundary is. Then you will put a
noisy neighbour next to both, crash the VM's kernel on purpose to see who notices, and
price your measurements on the Density Auction host from Session 7.

You are graded on **explaining your own measurements**, not on getting a particular number.
Two students with different laptops will get different numbers, and both can earn full
credit.

## What you need

- **Docker Desktop**, which you checked in the Environment Check in week 1.
- **Python 3.9 or newer on your laptop itself**, not inside a container, because the driver
  script has to start and stop your container and your VM from the outside. Check with
  `python3 --version` on macOS or Linux, or `py --version` on Windows. If you do not have
  it, install it from python.org. There is nothing to `pip install`.
- **A virtual machine.** How you get one depends on your laptop, and
  [VM-SETUP.md](VM-SETUP.md) walks through each case: Multipass on a Mac, a QEMU virtual
  machine that Docker starts for you on Windows 11 or Linux, Multipass with Hyper-V as an
  alternative on Windows Pro or Education, and Google Cloud's free tier if your laptop
  cannot run a VM at all. Nothing in this lab costs money.
- About **3 GB of free disk** and **2 GB of free memory** while it runs.

Budget about an hour for set-up, most of it downloads, and two to three hours for the
measurements and the report. **Do the VM set-up first, this week.** It is the only part
that can surprise you, and it is much easier to fix on a Tuesday than at 11 PM on the due
date.

## Getting the files

1. Open the
   [cs218-f26-lab2 repository on GitHub](https://github.com/handoyo-lyrid/cs218-f26-lab2).
2. Use it as a template, clone it, or take the **Download ZIP** option. GitLab, Codeberg and
   a downloaded archive are all equally fine, and none of them cost you anything.
3. Open a terminal in that folder.
4. Create a file named `student.txt` in that folder with your name on the first line and
   your SJSU ID on the second. It is listed in `.gitignore`, so it stays out of any public
   fork.

Every command below runs from that folder. Where this README says `python`, use `python3`
on macOS and Linux, or `py` on Windows.

## The workload

`app/app.py` is a small web service using only Python's standard library. It is the same
file in both places: `lab.py` checks that the copy in your container and the copy in your
VM are byte-for-byte identical to the one in this folder, so **do not edit it**.

It holds 64 MB of memory it has actually written to, so there is a known amount of tenant
memory to subtract when you measure overhead. It answers three requests:

| Path | What it does |
|---|---|
| `/health` | Answers immediately. The driver times start-up to the first answer here. |
| `/work` | Hashes 12.5 MB of data, the same fixed amount of CPU work every time. |
| `/probe` | Reports what the machine looks like from inside: which kernel, how much memory and how many CPUs it believes it has, who it is running as, and what limits it is under. |

## Part 0: Write the Dockerfile

There is no Dockerfile in this repository. Writing it is the first part of the lab, and it
is the version-controlled configuration that makes your container reproducible. Create a
file named `Dockerfile` in this folder that meets these six requirements:

1. **A pinned base image.** Name a specific tag, never `latest` and never no tag at all, so
   that the image you build next month is the image you built today.
2. **Python 3.12.** Your VM runs Ubuntu 24.04, whose Python is 3.12. Same program, same
   interpreter version, or the comparison is not fair.
3. **`app/app.py` copied in unchanged.**
4. **A non-root user.** The app needs no privileges, so it should not have any.
5. **A `HEALTHCHECK` that asks the app's `/health` path.** Slim images do not include
   `curl`; Python can make the request itself.
6. **An exec-form `CMD`**, written as a JSON array, so that `python` is the container's first
   process and receives the stop signal directly.

The Docker documentation's
[Dockerfile reference](https://docs.docker.com/reference/dockerfile/) covers every
instruction you need: `FROM`, `RUN`, `COPY`, `USER`, `EXPOSE`, `HEALTHCHECK` and `CMD`.
Then build it:

```
python lab.py build
```

This builds the image as `cs218-lab2` and records its size, its layers and what the
Dockerfile says. Requirements 2, 3, 4 and 6 are checked against the running container
later, not just read from the file. If a requirement is missing, `verify` names it.

## Set up your VM

Follow [VM-SETUP.md](VM-SETUP.md) for your laptop. When you finish, you will have four
things written down, and the rest of this README refers to them by these names:

| Name | What it is | Example (the Windows route) |
|---|---|---|
| `VM_URL` | where your VM's copy of the app answers | `http://127.0.0.1:8081` |
| `START` | the command that starts your VM | `docker start lab2-vm` |
| `STOP` | the command that stops your VM | `docker stop -t 60 lab2-vm` |
| `CRASH` | the command that crashes your VM's kernel | `docker exec lab2-vm vm-exec sudo lab2-panic` |

Check that `VM_URL` answers before you go on: open `VM_URL/health` in a browser.

## Running the lab

Run the parts in this order. Each prints what it is doing and writes its results into a
`results/` folder. Commands that take your values are shown with the Windows route's
values; substitute your own from VM-SETUP.md.

### Part 1: Start-up time

```
python lab.py container-start
python lab.py vm-start --url VM_URL --start "START" --stop "STOP" --hypervisor "what runs your VM"
```

The first starts your container ten times, each time from nothing, and times how long it
takes to answer `/health`. It leaves the last one running on port 8080, and the later parts
use it. The second stops and starts your VM three times and does the same. For
`--hypervisor`, say what actually runs the VM, for example
`"Multipass 1.16.4 on macOS 15, Apple Silicon"` or
`"QEMU with KVM in Docker Desktop, Windows 11 Home"`.

### Part 2: Memory

```
python lab.py memory --vm-url VM_URL --vm-host-mb N --vm-host-source "where you read N"
```

The container's cost to the host is read for you. The VM's cost to the host has to be read
from outside the VM, and where you read it depends on your hypervisor: VM-SETUP.md says
where to look, and `N` is that number in megabytes. On the Windows route, replace the last
two options with `--vm-docker lab2-vm` and it is read for you.

**Wait until your VM has been up for at least three minutes before running this.** A VM
that has just booted is still settling, and its numbers are inflated.

### Part 3: The isolation boundary

```
python lab.py probe --vm-url VM_URL
python lab.py crash --vm-url VM_URL --crash "CRASH"
```

`probe` asks both copies of the app the same questions and prints the answers side by side.
Rows marked `*` differ. Read every row before moving on.

`crash` then crashes your VM's kernel on purpose, while watching both the VM and your
container. The crash is done by a small program named `lab2-panic` that exists only inside
your VM and refuses to run anywhere else. The VM is configured to reboot itself ten seconds
after its kernel panics.

> **Only ever run `lab2-panic` through the `CRASH` command from VM-SETUP.md.** Never type a
> kernel-crash command into a terminal on your own laptop, into WSL, or into a container.
> On a Linux laptop that would crash your laptop, and on Windows or macOS it would take down
> Docker Desktop and every container in it. `lab.py` refuses any crash command that is not
> `lab2-panic`, and refuses to target anything that is not your Lab 2 VM.

### Part 4: A noisy neighbour

```
python lab.py neighbour --vm-url VM_URL
```

This sends 400 `/work` requests to each copy of the app in three phases: with nothing else
running, then next to a container running one busy loop per CPU, then next to the same busy
loops limited with `--cpus 1`. It takes a few minutes. Leave your laptop alone while it
runs, because anything else you do becomes part of the measurement.

### Part 5: Density on the auction host

There is nothing to run. Part 5 is the last question in the report, and it uses the
numbers Part 2 produced.

## Checking your work

```
python lab.py verify
```

This prints a checklist of ten items and writes `results/lab2-results.json`, which is one
of the two files you submit. It does not grade your report; it confirms that each part ran
and produced the evidence your report is supposed to be talking about.

An unticked box is not a disaster. Partial credit is real, and a clear written account of
something that would not work on your machine is worth considerably more than a blank
submission.

## What to write

Copy `report-template.md` to `report.md` and answer the five questions in it. The template
has the questions, the point values, and what a good answer contains. Roughly 900 to 1,300
words in total is the right size; there is no credit for length on its own.

Every question is about **your own run**, so answers must quote numbers from your own
`results/` folder. An answer built from someone else's numbers, or from the examples in
this README, will not match the results file you submit next to it.

## What to submit on Canvas

Two files, attached to the same submission:

1. `results/lab2-results.json`, written by `python lab.py verify`. It includes your
   Dockerfile, so there is no need to attach that separately.
2. `report.md`, or a PDF of it if you prefer.

If you used an AI tool, say which one and what you used it for in one line at the end of
the report. Disclosure is required and costs nothing.

Late work loses 10% per day, up to five days, and is not accepted after that, per the
syllabus.

## Cleaning up

When you have submitted, stop and delete what you created: your container with
`docker rm -f lab2-app`, and your VM as VM-SETUP.md describes for your route. The Google
Cloud route in particular: delete the VM, or its disk keeps counting against your free
tier.

## If it does not work

**`lab.py build` says there is no Dockerfile.** Part 0 is yours to write; see above.

**The container never answers on port 8080.** Something else on your laptop is using 8080,
or the app is crashing. `docker logs lab2-app` shows why. If the port is taken, stop
whatever holds it for the length of the lab.

**`verify` says a Dockerfile requirement is missing, but your file has it.** Some are checked
against the running container, not the file. Rebuild with `python lab.py build`, then run
`python lab.py container-start` again so the running container is the new image.

**`docker stop` takes about ten seconds every time.** That is a finding, not a failure:
something is between Docker and the app. Look at requirement 6, then at your `CMD` line.

**`vm-start` waits a long time on its first run.** A VM's first boot does its one-time
set-up. Let it finish, or boot it once by hand before timing it.

**`memory` says the VM booted less than two minutes ago.** Wait and run it again.

**Your VM does not come back after `crash`.** Some hypervisors hold a crashed VM rather than
restarting it. Start it with your `START` command; `crash` keeps waiting for up to ten
minutes and records how long it took.

**Everything is slower than the examples here.** That is expected on some machines and is
not a problem. Every question asks about your numbers, not mine.

**You are stuck for more than about thirty minutes.** Email me before the due date with what
you tried and what the error said. Getting stuck on the apparatus is not what this lab is
assessing.

## A note on the numbers

Nothing in this lab is simulated. The start-up times are real boots of a real kernel and
real starts of a real process; the memory figures are read from the host and from inside
the guest; the noisy neighbour is a real process competing for real CPUs. That also means
your numbers depend on your laptop, your operating system and your hypervisor, which is
exactly why the report asks you to explain them rather than to match anybody else's.
