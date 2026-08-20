# SharePoint Authorization Required

Status: `BLOCKED_ON_LEGAL_INTERACTIVE_LOGIN`

The two official OV-AVEBench SharePoint links require a legitimate Microsoft
organization login. Anonymous HTTP and Microsoft Graph probes do not expose the
archive bytes. No password, cookie, token, or MFA code may be pasted into this
repository or sent to the agent.

## Human action on the RTX 5090 host

1. Open an RDP session to the RTX 5090 host, or connect the Codex browser
   extension to an already authorized Chrome/Edge session on that host.
2. In the browser, open the official preprocessed-data URL:
   `https://mailhfuteducn-my.sharepoint.com/:u:/g/personal/2018110964_mail_hfut_edu_cn/Efm9NKaGQFBAsOC2ZOMZRvcB26TKXJ84H4VW6g8BR5SukQ?e=OPgMOt`
3. Complete Microsoft login/MFA in the browser and download the file without
   renaming or modifying it.
4. Open the official raw-video URL:
   `https://mailhfuteducn-my.sharepoint.com/:u:/g/personal/2018110964_mail_hfut_edu_cn/EcVHOp2zOyVHvi1Au-i1zFQBf5wQNi-Yff9Aso_SJ4MV8Q?e=OeRlQh`
5. Download that file without renaming or modifying it.
6. Place both downloaded files in:
   `E:\OV-OrthKD-R3\repo\data\downloads\manual_sources\`
7. Notify the agent only that the files are present. Do not send credentials.

After the files are present, the automated workflow will reject login HTML/XML/LFS
pointers, compute bytes and SHA256, create immutable archive receipts, safely
extract into staging directories, audit the official layout, and then publish the
verified trees. It will not trust the browser filename or content type by itself.
