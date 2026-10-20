# English Lab YouTube Video Download

This Chrome extension downloads a complete video to your computer so you can upload that file to the English Lab WhisperX tab. It does not record the browser tab. The extension sends the current YouTube page URL to a small helper running on your computer; the helper uses `yt-dlp` and saves the video in `Downloads/English Lab Videos`.

Use this only for videos you own or are authorized to download. It supports public, non-live videos up to two hours and 512 MB. The local downloader needs Python 3.10 or newer and FFmpeg installed and available on `PATH` so it can combine the highest available video and audio streams.

## One-time setup

1. Install FFmpeg and make sure `ffmpeg` is available in a new PowerShell window.
2. From the repository folder, start the helper:

   ```powershell
   .\browser-extension\start-helper.ps1
   ```

   On first run, the script creates an isolated Python environment and installs `yt-dlp`. Leave its PowerShell window open while downloading.
3. In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select the repository's `browser-extension` folder.

## Download and use in WhisperX

1. Open the YouTube video you are authorized to download.
2. Click the English Lab extension and choose **Tải video của tab này**.
3. A local progress tab opens. When it finishes, the full video is in `Downloads/English Lab Videos`.
4. In the English Lab Space, open **WhisperX · video/audio**, choose the downloaded video file, add the YouTube ID if you want to import its transcript into that lesson, and run WhisperX.

The local helper binds only to `127.0.0.1`; it does not upload the video anywhere. The video is sent to the Space only when you select it in the WhisperX upload field.
