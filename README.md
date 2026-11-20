# Clip Agent

Turn long YouTube videos (even 12-hour streams) into Shorts, TikToks and Reels, for free.
It runs on your own Windows PC and opens like a website in your browser.

- Finds the moments worth posting (hot takes, stories, funny bits, emotional peaks) and scores each one out of 50
- Splits long stories into Part 1 and Part 2, with a cliffhanger ending and a recap line
- Writes the on-screen text for each style, the hook, the post caption and hashtags
- Shows where every clip sits on a timeline of the whole video, and lets you preview each moment
- Makes finished 9:16 clips in three styles (meme caption, reaction split, bold captions), with a
  teaser opening, Part labels, pauses cut out and audio levelled for phones
- Downloads only the parts it needs. No watermark, no minute limits, no subscription.
- Updates itself every time you open it

## Install (Windows, about 5 minutes, one time)

1. Press the **Windows key**, type **PowerShell**, and open **Windows PowerShell**.
2. Paste this and press **Enter**:

   ```
   irm https://raw.githubusercontent.com/coder677777/clip-agent/main/install.ps1 | iex
   ```

3. Wait for "Done!". It installs Python if you don't have it, sets everything up, puts a
   **Clip Agent** icon on your desktop and in the Start menu, and opens the app.

From then on, just double-click the **Clip Agent** icon. It runs quietly in the background and
opens at http://127.0.0.1:8765. You can bookmark that.

## First time in the app

The app asks for a free Gemini key (the AI that picks the clips):
open https://aistudio.google.com/apikey, sign in, click **Create API key**, copy it, paste it in.

## Making clips

1. Paste a YouTube link, type how many clips you want (or turn on **As many as it finds**) and the
   average length in seconds, then press **Find clips**. The clips average out to the length you typed.
   You can also use a video file from your computer, or paste a clip plan from Claude.
2. Look through the clips. Each one shows a preview of how it will look, its score, hook,
   first and last words, and the post caption. **Preview the moment** plays it from YouTube.
3. Pick a style above the clips, fix any on-screen text by typing in the box, tick the clips you
   want, and press **Make clips**.
4. Each clip appears in the page when it's done. **Download clip** saves it, and
   **Open clips folder** shows all of them.

Styles:
- **Meme caption**: the clip in a square in the middle, with a lowercase "when…" line over it
- **Reaction split**: the streamer's face cam on top, the gameplay below, and a white headline box.
  It finds the face cam by itself; if it picks the wrong corner, choose the corner under **Face cam**.
  Videos with no face cam are made in the meme caption style instead.
- **Bold captions**: big word-by-word captions with a hook, in one of these layouts:

Bold caption layouts:
- **Blurred background**: any normal 16:9 video (default)
- **Full-screen crop**: one person in the middle of the frame
- **Split screen**: two people side by side (left person on top, right person on the bottom)

## If something goes wrong

- **"Too many requests" from YouTube**: wait 20-30 minutes, or in Settings choose the browser
  you're signed in to YouTube with. If captions stay blocked, the app transcribes the audio itself
  (slower, roughly 10 minutes per hour of video).
- **Gemini "free-tier limit"**: the free key has a daily cap. A 12-hour video uses about 12 requests.
- **The page won't open**: double-click the Clip Agent icon again. A log is in
  `%LOCALAPPDATA%\ClipAgent\clip-agent.log`.
- **Reinstall or repair**: run the install command again. Your key and clips are kept.

Clip your own videos, or channels that allow clipping. Reposting other people's content without
permission can get your account struck.

Your clips and settings live in `%LOCALAPPDATA%\ClipAgent`. Fonts: Poppins (SIL Open Font License).
