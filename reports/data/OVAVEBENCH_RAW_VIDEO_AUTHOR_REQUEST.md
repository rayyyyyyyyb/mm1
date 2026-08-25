# OV-AVEBench official raw-video correction request

> Optional diagnostic correspondence only. The final user-approved canonical reconstruction uses the official ten JPG keyframes plus WAV and does not execute raw-video decoding. No author response is required before canonical reproduction; do not treat the draft message below as a readiness blocker.

Recommended contact route: open an issue in the official `jasongief/OV-AVEL` GitHub repository, or send the same text through an author contact channel already known to the user. This repository does not send the message automatically.

## Ready-to-send message

**Subject:** 13 zero-byte MP4 members in the official OV-AVEBench raw archive

Hello OV-AVEL authors,

We downloaded the raw-video archive from the official SharePoint link in the OV-AVEL README. The download completed byte-for-byte and the gzip/tar container passes full sequential reads and 7-Zip testing:

- file: `OV-AVEBench_raw_videos.tar.gz`
- bytes: `38,147,170,955`
- SHA256: `ac9c8fc6e8b905ed414082132d6c2f8c81f5a8aad5d2c996e7512a40ff12b1bc`
- tar members: `25,020`
- regular files: `24,836`
- unsafe paths / duplicate destinations: `0 / 0`

However, the following 13 formal MP4 members have size zero. Could you please provide either (a) a corrected official raw archive, or (b) these 13 original MP4 files from an author-controlled location, together with SHA256 values or another author-issued checksum?

### Train

- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/train/arc welding/IUUe8-Zn9cA.mp4` — VGGSound start `249`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/train/people crowd/H3z1RRazXhc.mp4` — start `30`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/train/people crowd/YPisuHnthCo.mp4` — start `20`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/train/people crowd/fQWT4MDmVGw.mp4` — start `200`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/train/race car/7J8LMbtzJLs.mp4` — start `180`

### Validation

- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/arc welding/di01T0hGboU.mp4` — official VGGSound CSV has two candidates, starts `51` and `359`; we did not guess which one OV-AVEBench uses
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/basketball bounce/ri2DVH0Q-so.mp4` — start `40`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/basketball bounce/tm870k_Vr2s.mp4` — start `0`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/basketball bounce/u13LAp8oBUE.mp4` — start `256`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/church bell ringing/Uuti9EHClMk.mp4` — start `330`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/val/people crowd/4xR6HvjYEII.mp4` — start `30`

### Test

- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/test/basketball bounce/EDal0UtzjTA.mp4` — start `380`
- `Users/zhoujx/Documents/Research/AVEL/OpenVocabularyAVEL/ovave_dataset/test/female speech/bTpB0vwqb8M.mp4` — start `100`

The official preprocessed archive is complete (`24,618,769,924` bytes, SHA256 `ebecec9915052beffbba7ae1debd7b45cfef7b70fd7866196b964ab8542a413e`) and contains ten non-empty JPG frames plus one non-empty WAV for each of these 13 IDs. We will not use those derivatives, a YouTube recut, or a mirror as a substitute for the official raw MP4 bytes.

Our full ffprobe inventory also found that 1,019 non-empty formal videos have a video-stream duration below 10.0 seconds (588 below 9.5 seconds; minimum 1.2 seconds). The official metadata/file ID match is otherwise exact: 24,800/24,800, with no missing, extra, or duplicate formal IDs after excluding 25 macOS `._*.mp4` AppleDouble sidecars. The reconstruction protocol currently fails closed when a raw video cannot cover all ten one-second InternVideo2 intervals. Could you also clarify the official handling used for released clips shorter than ten seconds (for example, whether another author-owned raw source exists, or whether the official pipeline used a specific non-repeating boundary policy)? We will not guess padding, repetition, resampling, or replacement behavior.

Thank you.

## Intake and verification after author files arrive

Place individual files in a new overlay directory without changing the original downloaded archive:

`E:\OV-OrthKD-R3\repo\data\downloads\quarantine\ovave_author_replacements\`

Create a declaration JSON with one record per expected ID, using only `candidate_kind: author_sharepoint_file` (individual author files) or `candidate_kind: author_corrected_archive` (files safely extracted from a corrected author archive). Each record must contain `sample_id`, the exact `archive_member` above, an HTTPS author SharePoint `source_locator`, and the filename-only `file_path` relative to the overlay root.

On the 5090, put FFmpeg's `bin` directory on `PATH`, then run:

```powershell
python scripts/verify_ovave_raw_replacements.py `
  --declaration data/downloads/quarantine/ovave_author_replacements/declaration.json `
  --expected-manifest reports/data/ovave_raw_video_recovery_manifest.json `
  --output data/downloads/state/ovave_raw_replacement_audit.json
```

Exit `0` means all 13 author-issued files have the exact IDs, non-zero bytes, recomputed SHA256 values, decodable video and audio streams, approximately 10-second duration, and a complete unique set. Exit `2` remains blocked. Never overwrite or repack the original archive.

Even after the 13 files pass this verifier, keep the conference gate blocked until the authors clarify the shorter-video protocol or provide corrected author-issued bytes, and a fresh full raw-video layout audit passes the locked temporal policy.
