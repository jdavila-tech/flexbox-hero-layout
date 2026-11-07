# Skip Scanner

A small web app for your home server. Pick movies or TV episodes from your Plex folders, and it finds
scenes with nudity and creates skip files, so those scenes are skipped during playback. **Your
original video files are never changed.**

How a title is processed:

1. **Find candidates.** ffmpeg checks two frames per second, plus the first frame after every scene cut,
   so very short shots aren't missed. A local detector (NudeNet) flags anything that *might* be nudity.
   It is set to flag too much on purpose. Dark frames are brightened first so dark scenes aren't missed.
2. **Claude double-checks.** For each flagged scene, a few small frames (shrunk to 512 px) plus nearby
   subtitle lines go to Claude. Claude labels it: real nudity, swimsuit or underwear, shirtless man,
   statue or painting, medical, a baby's bath, a false alarm, and so on. Only the categories you choose
   are skipped. If Claude isn't sure, the scene waits for your review.
3. **Clean edges.** The start and end of each scene are checked again at 5 frames per second, then moved
   to the nearest scene cut, so skips don't cut in mid-sentence.
4. **Skip files** are written next to the video:
   - `Movie (2010).edl`: the skip list. Kodi reads it automatically.
   - `Movie (2010).skips.json`: the full record of every flagged scene and its decision.
5. **Optional, for Plex:** *Create Plex Family Edit* makes a second copy with those scenes cut out:
   `Movie (2010) - Family Edit.mkv`. Plex lists it under **Play Version**. It copies the video
   without re-encoding, so it's fast and loses no quality. It cuts on keyframes, always on the side
   that removes slightly more, never less.

> **Why the Family Edit:** Plex apps ignore `.edl` skip files. Kodi (including with the
> PlexKodiConnect add-on) and mpv can use them. In the Plex app itself, the Family Edit version is
> the way to skip scenes.

## Set up on the server

Needs Docker with the compose plugin.

```bash
cd plex-skip-scanner
cp .env.example .env
nano .env            # set the password, API key, your Plex folder paths, PUID/PGID
mkdir -p data
docker compose up -d --build
```

Open **http://SERVER-IP:6091** and sign in as `admin` with the password from `.env`.

- **PUID/PGID:** run `id` on the server as the user who owns the media files. The app needs write access
  to the media folders to save the skip files next to the videos.
- **No API key?** The app still works, but every flagged scene waits for your review instead of
  being sorted by Claude.
- **Cost:** only flagged scenes are sent, about 6 small frames each. A typical movie costs a few cents
  to tens of cents. Each title's `.skips.json` records the tokens used. Results are cached, so scanning
  again doesn't pay twice.
- **Privacy:** only the small frames of *flagged* scenes and nearby subtitle lines leave the server.
  Full videos never do.
- **Speed:** a 2-hour movie takes roughly 10–30 minutes on a typical home-server processor. Titles are
  processed one at a time, at low priority, and `cpus: 2.0` in `docker-compose.yml` keeps Plex
  and the Windows 98 emulator responsive. Raise it if you want faster scans.

## Using it

- **Movies / TV Shows tabs:** tick titles, or a whole show or season, then press **Scan selected**.
- **Queue tab:** progress, cancel, errors.
- **Click a title** to review it. Each flagged scene shows its time, Claude's label and how sure it was.
  - Pictures are **blurred** until you tap them.
  - **Skip / Keep** overrides Claude. **Adjust times** fixes the start or end.
  - Scenes Claude wasn't sure about are listed first. Until you decide, they follow
    `unreviewed_default` in `config.yaml` (default: skip).
  - **Add a scene it missed:** enter start and end times, like `1:02:03`.
- Your choices are kept when you scan a title again.
- If you edit an `.edl` by hand, the app won't overwrite it; it saves its version as `.edl.new`.

## Settings (`config.yaml`)

| Setting | What it does |
|---|---|
| `decisions.skip` | Categories that get skipped. Add `sexual_activity_no_nudity` to also skip sex scenes without nudity. |
| `decisions.confidence_threshold` | Below this (0–1), a scene waits for your review. |
| `decisions.unreviewed_default` | `skip` or `keep` for scenes still waiting for review. |
| `detection.threshold` | Detector sensitivity. Lower flags more (and costs more to review). |
| `review.model` | Claude model used for review. |
| `skips.padding_sec`, `snap_to_cut_sec`, `merge_gap_sec` | How skips are shaped. |

Restart after changing it: `docker compose restart`.

## Kodi

Kodi reads `Movie.edl` when it sits next to `Movie.mkv` and skips those parts automatically; no
setting is needed. Kodi has to play the file from the folder itself (a network share or local
path), because that's where it looks for the `.edl`. With PlexKodiConnect, that means **direct
paths** mode.

## Run without Docker (for testing)

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt     # also needs ffmpeg installed
MOVIES_DIR=/path/Movies TV_DIR=/path/TV DATA_DIR=./data CONFIG_PATH=./config.yaml \
APP_PASSWORD=secret uvicorn app.main:app --host 0.0.0.0 --port 6091
```

## Limits

- It detects visible nudity, plus sex scenes when you enable that category. It doesn't flag violence
  or language.
- Detection isn't perfect. Check the review list for the first few titles, and use *Add a scene it
  missed* if something slips through.
- Skipping content in your own copies for private home viewing is explicitly allowed in the US by the
  Family Movie Act of 2005.
