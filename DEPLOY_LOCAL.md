# Local deployment (code and VM are separate)

This repository contains source code, dependency manifests, and deployment
scripts. It intentionally excludes API keys, runtime outputs, OmniParser model
weights, and VMware images so a clone stays lightweight and safe to share.

## 1. Clone code and third-party dependencies

```powershell
git clone https://github.com/melonthrower/GUI-ReWalk-mobile.git
cd GUI-ReWalk-mobile
git checkout codex/minimal-local-deploy

git clone https://github.com/xlang-ai/OSWorld.git OSWorld
git clone https://github.com/microsoft/OmniParser.git OmniParser
```

Use Python 3.10 and Conda where possible:

```powershell
conda create -n guiwalk python=3.10 -y
conda activate guiwalk
pip install -r OSWorld/requirements.txt
pip install -e OSWorld
pip install -r requirements.txt
pip install -r OmniParser/requirements.txt
```

Download OmniParser weights according to its official instructions, including:

```text
OmniParser/weights/icon_detect/model.pt
OmniParser/weights/icon_caption_florence/
```

## 2. Place the VMware image

Extract the separately distributed VM archive so its main configuration is at:

```text
OSWorld/vmware_vm_data/Ubuntu0/Ubuntu0.vmx
```

Open that file in VMware Workstation and select “I moved it” on first launch.
Enable host virtualization and reserve at least 100 GB free disk space and 16 GB
RAM. Do not commit the VM to Git: GitHub blocks normal Git files over 100 MiB,
while this VM archive is approximately 12.8 GB.

## 3. Set credentials and run

Set the key only in the active PowerShell session; never write it into a script
or commit it:

```powershell
$env:DASHSCOPE_API_KEY = "<your-key>"
.\run_local_visual.ps1 -AppName setting -PythonExe python
```

The launcher derives the OSWorld, OmniParser, and VMware paths from the
repository directory. The first run uses a small traversal budget. A completed
traversal is indicated only by `frontier_empty`.

## 4. Distribute the VM

Use a trusted drive or file-sharing service for the VM archive. If GitHub
Releases is required, split the archive into volumes below 2 GiB and publish
SHA-256 checksums. Release assets do not download automatically with `git clone`.
