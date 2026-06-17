# 01 Dataset And Fine-Tuning

This document describes how to prepare a custom training set and fine-tune a YOLO model for deployment on Jetson.

## Goal

Produce a model that can be exported to TensorRT and run in the Jetson C++ pipeline without changing preprocessing semantics between training, validation, export, and deployment.

## Recommended Workflow

1. Define detection classes.
2. Collect and label images/videos.
3. Convert labels to YOLO detection format.
4. Split train/val/test.
5. Train or fine-tune with Ultralytics.
6. Validate model quality.
7. Export to TensorRT on Jetson.
8. Run target-resolution benchmark.

## Dataset Layout

Use a stable project layout:

```text
dataset_root/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
  data.yaml
```

Each image has a matching label file:

```text
images/train/000001.jpg
labels/train/000001.txt
```

YOLO label format:

```text
class_id x_center y_center width height
```

Coordinates are normalized to `[0, 1]` relative to image width and height.

Example:

```text
0 0.5124 0.4381 0.2712 0.1840
```

## `data.yaml`

Example:

```yaml
path: /data/my_dataset
train: images/train
val: images/val
test: images/test

names:
  0: person
  1: car
  2: truck
```

Keep class ids stable. Do not reorder `names` after training starts.

## Image Collection Guidance

Collect data that matches deployment conditions:

- Camera viewpoint and height
- Lens and distortion
- Lighting
- Motion blur
- Day/night/weather
- Target object scale
- Background clutter
- Occlusion
- Compression artifacts
- Real deployment resolution

For cascaded detection:

- Stage1 dataset should emphasize localization and recall.
- Stage2 dataset should emphasize type separation in cropped ROI images.
- If stage2 receives crops in deployment, train or fine-tune stage2 with similar crops, not only full images.

## Annotation Quality Checklist

- Every visible target is labeled unless the policy explicitly excludes it.
- Box edges are tight but not clipped too aggressively.
- Tiny or ambiguous objects have a consistent policy.
- Occluded objects are handled consistently.
- Class ids match `data.yaml`.
- Empty images have empty label files or no label files according to the chosen tooling.
- Train/val split has no near-duplicate leakage.

## Split Strategy

Recommended minimum:

```text
train: 70-80%
val:   10-20%
test:  10%
```

For video datasets, split by scene/video, not randomly by frame. Random frame splits often leak nearly identical frames into validation.

## Fine-Tuning Command

Example:

```bash
source ~/venvs/yolo-jetson/bin/activate
yolo detect train \
  model=yolo26n.pt \
  data=/data/my_dataset/data.yaml \
  imgsz=1024 \
  epochs=100 \
  batch=16 \
  device=0 \
  workers=8 \
  project=/data/runs \
  name=yolo26n_custom_1024
```

For a smaller stage2 crop model:

```bash
yolo detect train \
  model=yolo26n.pt \
  data=/data/stage2_crop_dataset/data.yaml \
  imgsz=416 \
  epochs=100 \
  batch=32 \
  device=0 \
  project=/data/runs \
  name=yolo26n_stage2_actual416
```

## Why `400` Becomes `416`

YOLO models commonly require image sizes divisible by max stride. For the tested YOLO26n model, max stride is 32.

`400 / 32 = 12.5`, so Ultralytics adjusts requested `400` to `416`.

For documentation and scripts, use:

```text
requested400_actual416
```

Do not claim strict `400x400` unless the model/export path proves that exact input shape.

## Training For Cascaded Detection

The cascade pipeline is:

```text
full frame -> stage1 location -> crop ROI -> stage2 type decision
```

Recommended training setup:

- Stage1:
  - high recall
  - fewer classes if possible
  - all objects that may need second-stage classification
  - loss/metrics judged mainly on localization and recall

- Stage2:
  - crop-level dataset
  - classes for actual content/type decision
  - crop generation should mimic production stage1 box noise
  - include negative/background crops if false positives matter

## Crop Dataset Generation

Use several crop sources:

- Ground-truth boxes
- Jittered ground-truth boxes
- Stage1 predicted boxes from a held-out set
- False-positive boxes from stage1

Example crop policy:

```text
scale box by 1.05-1.25
clamp to image boundaries
letterbox crop to stage2 input size
preserve original class label for stage2
```

## Validation Metrics

Track:

- mAP50-95
- precision/recall
- per-class confusion matrix
- false positives per frame
- missed detections per scene
- latency at target resolution
- TensorRT exported model accuracy if possible

For cascade:

- stage1 recall at target threshold
- stage1 localization quality
- stage2 classification accuracy on stage1-generated crops
- full cascade end-to-end accuracy

## Common Mistakes

- Training on full images but deploying stage2 on crops.
- Changing letterbox color or padding policy between training and deployment.
- Reporting requested `400` when actual exported engine is `416`.
- Validating PyTorch only, but deploying TensorRT without accuracy checks.
- Mixing class orders between datasets.
- Letting near-duplicate video frames leak into validation.
