# Obtaining model weights (offline installation)

SafeFace **never downloads anything at runtime**. An administrator fetches the
files below on an internet-connected machine, verifies them, carries them to
the air-gapped server on approved media, and records the SHA-256 in
`models/registry.yaml`. A file whose hash is missing or different is refused.

Licences: read `docs/LICENCES.md` first. TruFor, InsightFace models and
(probably) NPR are **non-commercial / research-only**.

## 0. Procedure for every file

1. Download on the connected machine (commands below).
2. Compute `sha256sum <file>` and compare with the hash in this document /
   `models/registry.yaml`. Where the registry has `sha256: null`, there is no
   published hash: record the one you computed, have a second person verify
   it independently, and log both names in the change register.
3. Copy to the server as `models/<path>` (path from the registry).
4. Restart the API: it re-reads the registry and audits any change
   (`registry.entry_added` / `registry.entry_changed`).
5. **Administration → Model registry** must show the entry as *ready*.

## 1. UnivFD (`image.aigen.univfd`) — MIT

```sh
# CLIP ViT-L/14 (OpenAI). The SHA-256 is part of the official URL itself.
curl -LO https://openaipublic.azureedge.net/clip/models/b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt
sha256sum ViT-L-14.pt   # b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836
# -> models/clip/ViT-L-14.pt

git clone https://github.com/WisconsinAIVision/UniversalFakeDetect && cd UniversalFakeDetect
git checkout 030495aea3300a8b54c0ec37ec7fe1dd7e63c619
sha256sum pretrained_weights/fc_weights.pth   # 477100745713bcc957beb2b40859536859b6483fd6301b3b9293151b194c7847
# -> models/univfd/fc_weights.pth
```

## 2. NPR (`image.aigen.npr`) — no licence file upstream

```sh
git clone https://github.com/chuangchuangtan/NPR-DeepfakeDetection && cd NPR-DeepfakeDetection
git checkout 781ced3f7ca2cdc69ec9dd4ef27e8d0b3c07752a
sha256sum NPR.pth   # 3939297e9399e0b992f87211610769d87d899de50d56da0204d6cbda2d483a53
# -> models/npr/NPR.pth
```
SafeFace's re-implementation was verified to load this checkpoint with
`strict=True` and `weights_only=True` (test `test_real_npr_checkpoint_loads_strictly`).

## 3. TruFor (`image.trufor`) — GRIP-UNINA non-profit licence

Two files: the upstream inference **source** (not shipped in this repository
because of its licence) and the **weights**.

```sh
git clone https://github.com/grip-unina/TruFor && cd TruFor
git checkout ae54475df6f41a491d7615100feb19263dec13f7
git archive --format=tar -o trufor-src-ae54475.tar ae54475df6f41a491d7615100feb19263dec13f7 test_docker/src
sha256sum trufor-src-ae54475.tar   # c3d1a7cc43cb243eca307724e7d64d2387ffd302972869f20c01ea5a590953eb
# -> models/trufor/trufor-src-ae54475.tar
#    (git archive output is stable for a given commit; if your hash differs,
#     inspect the tar contents, record your hash and have it second-checked)

curl -LO https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip
unzip TruFor_weights.zip      # -> weights/trufor.pth.tar
sha256sum weights/trufor.pth.tar   # no published hash: record it in registry.yaml
# -> models/trufor/trufor.pth.tar
```
SafeFace supplies minimal stand-ins for the two `yacs`/`timm` symbols the
upstream code imports, so neither package is installed.
If the checkpoint cannot be loaded with `weights_only=True`, the module
refuses it. After reviewing the file's origin, an admin may add
`allow_pickle: true` under that entry's `validation:` block (audited).

## 4. InsightFace ArcFace (`image.source_match`, optional face identity)

```sh
curl -LO https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip buffalo_l.zip -d buffalo_l
sha256sum buffalo_l/det_10g.onnx buffalo_l/w600k_r50.onnx   # record both in registry.yaml
# -> models/insightface/buffalo_l/det_10g.onnx
# -> models/insightface/buffalo_l/w600k_r50.onnx
```
Only these two files are loaded, each individually checksum-verified.
SafeFace does not use InsightFace's `FaceAnalysis` loader (it would load every
`.onnx` in the folder unverified and download missing models).

## 5. Transfer checklist

- [ ] Files copied to `models/` at the registry paths, read-only (`chmod 0444`).
- [ ] `sha256sum` re-run **on the server** matches the registry.
- [ ] Registry change recorded (who, when, source URL, both hashes).
- [ ] API restarted; Model registry page shows *ready*; a test analysis succeeds.
- [ ] Validation summary updated after the Phase 4 benchmark run.
