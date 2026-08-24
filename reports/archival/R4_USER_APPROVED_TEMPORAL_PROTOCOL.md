# R4 User-Approved Temporal Protocol

Date: 2026-08-24

## Status and scope

This document records the user's controlling interpretation for the current
reproduction, code audit, and documentation correction. It supersedes the R3
raw-video-only interpretation for the temporal protocol and InternVideo2 input
path. The other R3 approved reconstruction assumptions remain unchanged unless
another fact is explicitly replaced here.

## Approved protocol

- OV-AVEBench uses the official task timeline of exactly ten one-second
  temporal segments for every ten-second video.
- Labels, student segment logits, temporal teacher features, and inputs to F1,
  AP, and AUROC must all remain aligned to these ten task segments.
- No label interpolation, copying, resampling, or relabelling from ten to
  sixteen segments is permitted.
- The student model's historical `max_segments=16` is interpreted as a
  positional-embedding capacity. It is now named `max_position_segments` and
  must not be presented as the task timeline.
- The historical InternVideo2 wrapper and configuration establish
  `num_frames=8`. With the released OV-AVEBench representation, each of the ten
  official segment keyframes is deterministically repeated to those eight
  model input frames.
- No evidence establishes that every one-second segment was decoded at sixteen
  frames. The later 16-fps raw-video grid is retained only as an optional,
  disabled diagnostic protocol and is not a canonical data requirement.
- The paper phrases “16 fps”, “16 temporal segments”, and “per-16-seg clip” are
  treated as a systematic terminology ambiguity involving sampling or model
  capacity, not as authority to change the official ten-segment labels.

## Direct code evidence

- Initial repository commit:
  `dca9f052fbe4a1e9d7982f24bdcec3edf1363fd4`.
- Initial InternVideo2 wrapper blob:
  `dc833ad4a0560867f191d8305c405a62582d94a9`. It consumes frame groups,
  defaults to `num_frames=8`, and repeats a shorter group to eight frames.
- Initial student model blob:
  `27262ed5ead0fa460639ee7bd3cbc273500cfbbe`. It allocates positional capacity
  for sixteen entries but slices that tensor using the actual input sequence
  length.
- The official OV-AVEBench loader requires and loads ten ordered visual frames;
  the released annotations audited in this project also contain ten binary
  labels for all 24,800 samples.

## Consequences

Canonical manifests and teacher export may proceed from the fully audited
official JPG/WAV release without requiring a valid raw MP4. Missing, zero-byte,
or short raw videos remain recorded facts and block only an explicitly enabled
raw multiframe diagnostic. The full formal training guard remains active until
the source manifests, complete teacher cache, artifact audit, and single real
optimizer-step preflight have passed their separate readiness gates.
