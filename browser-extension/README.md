# English Lab YouTube media download

The local helper downloads an authorized YouTube source to your device. It can save audio only (smaller, recommended for WhisperX) or the full video. It downloads the source stream from the URL; it does not record the sound playing in a browser tab. Each file is limited to two hours and 512 MB.

## Android Chrome

Chrome for Android does not run this desktop extension. On Android, run the helper in Termux and use its local page in Chrome.

1. Install Termux from one of the sources listed in the [Termux installation guide](https://github.com/termux/termux-app#installation). If you already have Termux or its add-ons, install them from the same source; the signed builds cannot be mixed.
2. Open Termux and run:

   ```sh
   pkg update -y && pkg install -y git
   git clone --depth 1 --branch feature/english-lab-v21 https://github.com/mr2along/english.git ~/english-lab
   cd ~/english-lab
   bash browser-extension/start-helper-android.sh
   ```

   On first launch, Android may ask Termux for shared-storage access. Allow it and run the last command again. The helper installs Python, FFmpeg, and `yt-dlp`, then saves files under `Downloads/English Lab Videos`.
3. Keep Termux running. In Chrome on the same phone, open `http://127.0.0.1:8765`, paste the YouTube URL, and choose **audio only** or **full video**.
4. When the local page reports completion, open the [English Lab Space](https://huggingface.co/spaces/Mrlongpro/autosubs), open **WhisperX · video/audio**, select the saved file from Downloads, and run WhisperX. The downloaded file starts at the video's beginning, so timestamps use the same 00:00 origin.

The helper is bound to `127.0.0.1` and keeps the media on the phone until you choose it in the Space upload field. Android may stop Termux in the background; keep it open while downloading. Only download videos you own or are authorized to use.

## Desktop Chrome

The Chrome extension and helper below are for desktop Chrome. The helper requires Python 3.10+; FFmpeg is needed to combine the separate video and audio streams for a full video download.

On Windows, install FFmpeg, open PowerShell in the repository folder, and start the helper:

```powershell
.\browser-extension\start-helper.ps1
```

In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select `browser-extension`.

Open an authorized YouTube video, click the English Lab extension, then choose **Tải video của tab này**. When the download finishes, select it in the Space's **WhisperX · video/audio** tab.

On macOS or Linux, create a virtual environment, install the helper requirements, and run the helper from the repository folder:

```sh
python3 -m venv browser-extension/.venv
browser-extension/.venv/bin/python -m pip install -r browser-extension/requirements.txt
browser-extension/.venv/bin/python browser-extension/local_video_helper.py
```

Then load `browser-extension` unpacked in desktop Chrome as above.
