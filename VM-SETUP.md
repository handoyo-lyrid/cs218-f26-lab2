# Lab 2: setting up your virtual machine

Every route below ends in the same place: an Ubuntu 24.04 virtual machine with 1 CPU and
1 GB of memory, running the same `app/app.py` as your container, installed from the same
file, `vm/cloud-init.yaml`. Only the hypervisor underneath differs, and that difference is
part of what your report explains.

Pick your route from this table, follow that section only, and write down the four values
at its end.

| Your laptop | Route |
|---|---|
| Mac, Apple Silicon or Intel | [Route M: Multipass](#route-m-mac-multipass) |
| Windows 11, any edition, with Docker Desktop | [Route W: a QEMU VM that Docker starts](#route-w-windows-11-a-qemu-vm-that-docker-starts) |
| Windows 11 Pro or Education, if you would rather use Hyper-V | [Route H: Multipass with Hyper-V](#route-h-windows-pro-or-education-multipass-with-hyper-v) |
| Linux | [Route W](#route-w-windows-11-a-qemu-vm-that-docker-starts) works unchanged |
| Windows 10 Home, a Chromebook, or anything the routes above refuse | [Route G: Google Cloud](#route-g-google-cloud) |

**One warning that applies to every route:** `multipass launch lts` and similar shortcuts now
give you Ubuntu 26.04, not 24.04. Use the exact commands below, which name `24.04`.

**Do not use VirtualBox on Windows for this lab.** Docker Desktop keeps Windows' own
hypervisor switched on, VirtualBox runs very slowly alongside it, and reaching a VirtualBox
VM's port from Windows needs administrator-level port forwarding. Route W avoids all of
that.

---

## Route M: Mac, Multipass

Multipass is Canonical's free tool for Ubuntu VMs. On a Mac it runs them with QEMU on top of
Apple's own Hypervisor framework, so your VM gets hardware-assisted virtualization. It needs
macOS 13 or later.

**Install.** Download the macOS installer from
[canonical.com/multipass/install](https://canonical.com/multipass/install) and run it, or,
if you use Homebrew, run `brew install --cask multipass`. Check it with:

```
multipass version
```

**Create the VM.** From this lab's folder:

```
multipass launch 24.04 --name lab2 --cpus 1 --memory 1G --disk 10G --cloud-init vm/cloud-init.yaml
multipass exec lab2 -- cloud-init status --wait
```

The first command downloads Ubuntu (about 600 MB) the first time. The second waits until the
VM has finished installing the app, and should end with `status: done`.

**Find its address:**

```
multipass info lab2
```

Note the `IPv4` line, for example `192.168.64.5`. Open `http://192.168.64.5:8080/health` in a
browser to check it answers. If you use a VPN, turn it off for this lab: some VPNs capture
the `192.168.64` addresses Multipass uses.

**Where to read the VM's memory for Part 2.** The whole VM is one process on your Mac, named
`qemu-system-aarch64` on Apple Silicon and `qemu-system-x86_64` on an Intel Mac. Either open
Activity Monitor, choose the Memory tab and search for `qemu`, or run:

```
ps -axo rss,comm | grep qemu-system
```

The first number is its resident memory in kilobytes; divide by 1024 for megabytes. Use
that as `--vm-host-mb`, and say where you read it in `--vm-host-source`. Note that
`multipass info` also prints a memory figure. That one is the guest's own view from inside,
which is a different number, and the difference between the two is worth a sentence in your
report.

**Your four values:**

| | |
|---|---|
| `VM_URL` | `http://<the IPv4 address>:8080` |
| `START` | `multipass start lab2` |
| `STOP` | `multipass stop lab2` |
| `CRASH` | `multipass exec lab2 -- sudo lab2-panic` |

**When you are done with the lab:** `multipass delete --purge lab2`

---

## Route W: Windows 11, a QEMU VM that Docker starts

This route uses the hypervisor already built into your laptop. Docker Desktop on Windows 11
runs inside WSL2, and WSL2 lets the programs inside it use hardware virtualization
themselves. The lab's `vm/qemu` folder packages QEMU, a widely used open-source hypervisor,
into a container that boots a real Ubuntu VM with KVM: its own kernel, its own virtual
hardware, its own firmware. The container is only how the VM is delivered; what you measure
is the VM inside it.

Because the VM runs inside WSL2's own virtual machine, it is a VM inside a VM. That is
called nested virtualization. It works, and it costs something, and your report should say
so when it explains your start-up time.

**Check that your laptop can do it.** In PowerShell, from this lab's folder:

```
docker run --rm --device /dev/kvm alpine:3.20 ls -l /dev/kvm
```

If that prints a line beginning with `crw`, you are set. If it fails with an error about
`/dev/kvm`, your Windows does not offer nested virtualization (Windows 10 does not): use
Route H if you have Windows Pro or Education, otherwise Route G.

**Build and start the VM:**

```
docker build -t cs218-lab2-vm vm/qemu
docker run -d --name lab2-vm --device /dev/kvm -p 8081:8080 -v cs218-lab2-vm:/vm -v "${PWD}/vm:/lab2:ro" cs218-lab2-vm
```

That second command is for PowerShell. In the older Command Prompt, write `%cd%` in place of
`${PWD}`. On a Linux laptop, `$(pwd)`.

The first start downloads Ubuntu (about 600 MB) into a Docker volume and then boots it, and
the VM's first boot installs the app. Allow two or three minutes, then open
`http://127.0.0.1:8081/health` in a browser. Port 8081 is the VM; your container will use
8080. If it is not answering after five minutes, `docker logs lab2-vm` shows what happened,
and `docker exec lab2-vm tail -20 /vm/console.log` shows the VM's own boot messages.

**Where to read the VM's memory for Part 2.** You do not have to: on this route, run the
memory step as `python lab.py memory --vm-url http://127.0.0.1:8081 --vm-docker lab2-vm` and
it reads the QEMU process's resident memory for you.

**Your four values:**

| | |
|---|---|
| `VM_URL` | `http://127.0.0.1:8081` |
| `START` | `docker start lab2-vm` |
| `STOP` | `docker stop -t 60 lab2-vm` |
| `CRASH` | `docker exec lab2-vm vm-exec sudo lab2-panic` |

`STOP` gives the VM up to 60 seconds to shut down cleanly: Docker passes the stop on to the
VM as a press of its power button, the way you would shut down a real machine.

**When you are done with the lab:**

```
docker rm -f lab2-vm
docker volume rm cs218-lab2-vm
```

---

## Route H: Windows Pro or Education, Multipass with Hyper-V

An alternative to Route W for Windows editions that include Hyper-V, Microsoft's own
hypervisor. (Windows Home does not include it.) Here your VM runs directly on Hyper-V, beside
Docker Desktop's WSL2 virtual machine rather than inside it, so it is not nested.

**Turn on Hyper-V**, if it is not on already. In PowerShell run as administrator, then
restart:

```
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

**Install Multipass** from [canonical.com/multipass/install](https://canonical.com/multipass/install),
running the installer as administrator. Multipass will not start if Windows considers your
current network public, so make sure your network is set to private. Check with
`multipass version`.

**Create the VM, and find its address**, exactly as in Route M:

```
multipass launch 24.04 --name lab2 --cpus 1 --memory 1G --disk 10G --cloud-init vm/cloud-init.yaml
multipass exec lab2 -- cloud-init status --wait
multipass info lab2
```

**Where to read the VM's memory for Part 2.** Hyper-V shows a running VM's memory as a
process usually named `vmmem`. Open Task Manager, Details tab, and look for it, or run in
PowerShell:

```
Get-Process vmmem* | Select-Object Name, Id, @{n='MB';e={[int]($_.WorkingSet64/1MB)}}
```

WSL2 appears there too, as `vmmemWSL`; it is Docker Desktop's VM, not yours. If you see no
`vmmem` process for your VM, Hyper-V Manager's "Assigned Memory" column is the fallback; say
which you used.

**Your four values:** the same as Route M.

**When you are done with the lab:** `multipass delete --purge lab2`

---

## Route G: Google Cloud

For a laptop that cannot run a VM. Google Cloud's free tier includes one small `e2-micro` VM
a month in some US regions, and that machine has 1 GB of memory, the same size as everyone
else's lab VM (it has two virtual CPUs rather than one, which is worth a sentence in your
report). The course's Google Cloud education coupon, linked in Course Resources on
Canvas, sets up the billing account the free tier needs without a credit card. Done as
written, this route costs nothing.

You will do everything in **Cloud Shell**, the terminal built into the Google Cloud console:
it already has Docker, Python and the `gcloud` command, and it runs in your browser. Your
container runs in Cloud Shell; your VM runs on Compute Engine.

**In Cloud Shell,** get the lab's files there (clone your copy of the repository, or upload
the ZIP), `cd` into the folder, and run:

```
gcloud config set project YOUR_PROJECT_ID
gcloud compute instances create lab2 --zone=us-west1-b --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=10GB --boot-disk-type=pd-standard --tags=cs218-lab2 \
  --metadata-from-file=user-data=vm/cloud-init.yaml
gcloud compute firewall-rules create cs218-lab2-8080 --network=default --direction=INGRESS \
  --allow=tcp:8080 --target-tags=cs218-lab2 --source-ranges="$(curl -s https://ifconfig.me)/32"
```

The firewall rule lets only your Cloud Shell reach the VM's port 8080. Cloud Shell's
address can change between sessions; if the VM stops answering after you come back the next
day, delete the rule (`gcloud compute firewall-rules delete cs218-lab2-8080`) and create it
again.

A stopped Compute Engine VM usually gets a new external address when it starts again, so
this route gives the driver a command that looks the address up, and puts `{ip}` in the URL
where the address goes. For Part 1, run:

```
python3 lab.py vm-start --url "http://{ip}:8080" \
  --ip-cmd "gcloud compute instances describe lab2 --zone=us-west1-b --format='get(networkInterfaces[0].accessConfigs[0].natIP)'" \
  --start "gcloud compute instances start lab2 --zone=us-west1-b" \
  --stop "gcloud compute instances stop lab2 --zone=us-west1-b" \
  --hypervisor "Google Compute Engine e2-micro"
```

For the other parts, look the address up once with that `describe` command and use
`http://<address>:8080` as `VM_URL`.

**Before Part 3,** run `gcloud compute ssh lab2 --zone=us-west1-b --command "true"` once by
hand. The first time, it creates an SSH key for you and asks questions; the crash step
cannot answer them, so they have to be answered beforehand.

**Where to read the VM's memory for Part 2.** You cannot: the host is Google's, and nothing
about it is visible to you. Use what you are billed for, which is the machine's full
memory: `--vm-host-mb 1024 --vm-host-source "e2-micro billed size; host side not visible"`.
Your report should say what that means for your Part 2 and Part 5 answers.

**What will be different on this route, and is fine:** your container and your VM are on
different machines, so in Part 4 the busy loops in Cloud Shell cannot reach your VM at all.
Say so, and say why. Your start-up time includes Google's control plane finding a host for
your VM, not only the boot. Both are findings, not failures.

**Your four values:**

| | |
|---|---|
| `VM_URL` | `http://<external address>:8080` |
| `START` | `gcloud compute instances start lab2 --zone=us-west1-b` |
| `STOP` | `gcloud compute instances stop lab2 --zone=us-west1-b` |
| `CRASH` | `gcloud compute ssh lab2 --zone=us-west1-b --command "sudo lab2-panic"` |

**When you are done with the lab, delete everything**, because a stopped VM's disk still
counts:

```
gcloud compute instances delete lab2 --zone=us-west1-b
gcloud compute firewall-rules delete cs218-lab2-8080
```

---

## Checking the VM before you start

Whichever route you took, open `VM_URL/probe` in a browser. You should see a page of JSON in
which `kernel.release` ends in `-generic` or `-gcp`, `os_release` says Ubuntu 24.04, and
`virtualization.lab2_vm_marker` is `true`. If all three hold, go back to the README and start
Part 1.
