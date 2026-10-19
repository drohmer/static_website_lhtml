# lhtml-site

Slides and static websites written in [LHTML](https://github.com/drohmer/lhtml),
a light markup, with Jinja2 templates. Each page is a short text file; the
generator builds the HTML site (slides shown in the browser, or a website with
a menu), and optionally a PDF of the slides. It was named `static_website_lhtml`.

## Getting started: your first slides

**What you need**: Python 3.11 or newer ([python.org](https://www.python.org/downloads/)),
and [pipx](https://pipx.pypa.io/stable/installation/), which installs
commands written in Python: `brew install pipx` on macOS, `sudo apt install
pipx` on Debian or Ubuntu, `py -m pip install --user pipx` on Windows; then
`pipx ensurepath`, and open a new terminal. (Without pipx, see
[Installation](#installation).)

**1. Install lhtml-site and create a talk.** In a terminal:

```bash
pipx install lhtml-site
lhtml-site init my-talk --theme slides
cd my-talk
lhtml-site --serve --watch
```

`init` creates a directory `my-talk/` with a configuration and four slides
to start from:

```
my-talk/
  configure.yaml                     the configuration
  src/
    01_title/index.html.j2           a title slide
    02_text/index.html.j2            a slide of text: lists, math, a link
    03_two_columns/index.html.j2     two columns
    04_image/index.html.j2           text, and an image on the right
```

**2. Show it.** `lhtml-site --serve --watch` builds the slides and shows them
at <http://127.0.0.1:8000/>: open that address in your browser, and go from
slide to slide with the arrow keys. **Keep this terminal open while you
work**: each time you save a file, the slides are rebuilt; refresh the
browser to see the change. To stop, press Ctrl+C in the terminal.

**3. Add a slide.** A slide is a directory of `src/` with a file
`index.html.j2` in it. Duplicate `src/02_text` (in your file explorer, or
`cp -r src/02_text src/05_my_slide` in a second terminal) and name the copy
`05_my_slide`. The slides follow the order of their directories, hence the
numbers: `05_my_slide` comes last; name it `02b_my_slide` to put it after
`02_text`.

**4. Write it.** Open `src/05_my_slide/index.html.j2` in a text editor, and
replace its content with:

```
= My first slide

* A first idea
* An **important** point
* A conclusion
```

Save, and refresh the browser. The line starting with `=` is the title of
the slide (and its name in the menu); each `*` starts a bullet point
(`**` at the start of a line, a point under the one before); `**...**`
around words is bold, `__...__` italic.

**5. Put an image in it.** Copy your image, say `photo.png`, into
`src/04_image/assets/`; then, in `src/04_image/index.html.j2`, replace
`img::assets/diagram.svg` with `img::assets/photo.png`, and the caption on
the line `credit::` with yours. Save: the image is on the right of the
slide, fitted to its column. An image belongs to the
directory of its slide, in `assets/`.

The four slides of the start show the rest, each in a few lines: the title
slide, then math (`\(e^{i\pi} + 1 = 0\)`), a link, a space (`gap::`) and
small text in `02_text`, two columns (`cols::` and `col::`) in
`03_two_columns`, an image beside the text in `04_image`. All the macros
and layouts of the slides are in
[Design](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#design-tokens-macros-and-layouts),
and the markup in [LHTML](https://github.com/drohmer/lhtml).

**6. Come back to it later.** Open a terminal, go into the directory of the
talk, and start the preview again:

```bash
cd my-talk
lhtml-site --serve --watch
```

**7. Share it.** Your talk is `configure.yaml` and `src/`: keep them (a
backup, or a git repository). The slides themselves are built into `.site/`,
which `lhtml-site` (without `--serve`) rebuilds from them at any time. To
show the slides on another computer, copy the directory `.site/`: opening
`.site/index.html` in a browser shows them, no server needed; to put them
online, copy `.site/` to any web host (GitHub Pages, the server of your
university). The file explorer hides `.site/`, as any name starting with a
dot: Cmd+Shift+. shows it in the Finder, and *Hidden items* in the *View*
menu of the Windows explorer. For a PDF of the slides, see
[Your talk as a PDF](#your-talk-as-a-pdf).

To order the slides without renaming them, or to reuse a slide, list them in
a [deck](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#deck-order-of-the-slides).

**Other starts**:

- A website (documentation, a course) rather than slides:
  `lhtml-site init my-site` (theme `webpage-frame`, two pages to start from).
- *You already have your pages* in a directory `src/`: in the directory that
  contains `src/`, run `lhtml-site init --theme slides`. It writes only
  `configure.yaml` there; nothing else is created or changed.
- From a checkout of the generator (a submodule of the project),
  `python <checkout>/generate.py` takes the place of `lhtml-site`.

**The themes** (`--theme` of `init`, or the key `theme:` of `configure.yaml`):

| Theme | For | Needs |
|---|---|---|
| `webpage-frame` (default) | Web pages: documentation, a course website, with a navigation menu | nothing more |
| `slides` | Slides shown in the browser, 1920x1080, one page per slide | nothing more |
| `slides-pdf` | The same slides, exported to a PDF, with an image of each slide | Node.js, puppeteer and Chrome, poppler, ImageMagick: see [PDF export](#pdf-export) |

Change the theme at any time by editing `theme:`; it also takes the
directory of a theme of your own. To publish the same slides both in the
browser and as a PDF, see
[Decks and targets](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#decks-and-targets).

## Installation

```bash
pipx install lhtml-site                  # the command lhtml-site, in an environment of its own
pipx upgrade lhtml-site                  # later, to update it
```

Without pipx, in a virtual environment (Homebrew and recent system Pythons
refuse a `pip install` outside one). On macOS and Linux:

```bash
python3 -m venv ~/.venvs/lhtml-site
source ~/.venvs/lhtml-site/bin/activate     # fish: activate.fish
python -m pip install lhtml-site
```

On Windows, in PowerShell:

```powershell
py -m venv $HOME\.venvs\lhtml-site
& $HOME\.venvs\lhtml-site\Scripts\Activate.ps1
python -m pip install lhtml-site
```

The command `lhtml-site` is then there while that environment is active
(the `source` or `Activate.ps1` line again, in a new terminal).
`lhtml-site --version` says the version installed, and the LHTML it runs.
The version of `main`, before its release:
`pipx install git+https://github.com/drohmer/lhtml-site`.

**Python**: 3.11 or newer. **Required**, and installed with it: `lhtml-markup`
(3.0 or later), `Jinja2`, `jinja-markdown`, `pytidylib`, `pyyaml`, `rich`.
That is all a site of HTML pages or slides needs: no Node, no browser, no
other program.

**Optional features** each need their own tools. `lhtml-site doctor` says,
for each feature, what it finds and the command that installs what is
missing, for the way lhtml-site is installed:

| Feature | Needs |
|---|---|
| PDF export (`slides-pdf`) | Node.js, puppeteer and minimist, Chrome, poppler (`pdfunite`, `pdftoppm`), ImageMagick (`magick`) |
| Layout report (`--layout`, `--render`) | Node.js, puppeteer and minimist, Chrome |
| Videos in several codecs (`cache_video_directory:`) | `ffmpeg`, and `ffpb` (Python) |
| SASS (`.sass` files) | `libsass` (Python) |
| Figures in code (`*.svg.py`, `*.svg.tex`) | the libraries their scripts import, such as `matplotlib`, `numpy` (Python); `latex` and `dvisvgm` (TeX Live) |
| Code of other repositories (`code_include.py`) | `git` |
| HTML cleaned by tidy (`use_tidy: true`) | the library `libtidy` |

**Python packages after pipx.** pipx installs lhtml-site in an environment
of its own: `pip install matplotlib` puts the package into another Python,
and the generator still does not find it. Inject the packages into its
environment instead:

```bash
pipx inject lhtml-site matplotlib numpy          # figures in code
pipx inject lhtml-site libsass                   # SASS
pipx inject --include-apps lhtml-site ffpb       # videos (a command: --include-apps)
```

In a virtual environment or a checkout, `pip install matplotlib numpy` (and
`libsass`, `ffpb`) in the Python that runs the generator does the same.

### PDF export

The PDF export (and the layout report) run Chrome through Node.js and
puppeteer. The export writes `<deck>.pdf` (`slides.pdf` for a project of one
deck) and `images/` (an image of each slide) next to the site directory of
the target. With pipx (or pip), on macOS:

```bash
brew install node poppler imagemagick
npm install --prefix ~/.lhtml-site puppeteer minimist
~/.lhtml-site/node_modules/.bin/puppeteer browsers install chrome
lhtml-site doctor                                # PDF export: ready
```

On Debian or Ubuntu, the first line is
`sudo apt install nodejs npm poppler-utils`, with ImageMagick 7 (the command
`magick`) from <https://imagemagick.org>. The generator finds the Node
modules of `~/.lhtml-site/node_modules` by itself: no `NODE_PATH` is needed
(a `NODE_PATH` of yours is still read, first). The third line downloads the
Chrome of this version of puppeteer (over 100 MB): recent npm versions do not
run the install script of puppeteer, hence the explicit download. The PDF
export needs it; the layout report can do without it (the configuration key
`chrome`, or `PUPPETEER_EXECUTABLE_PATH`, names a Chrome already installed,
and a Chrome installed in the usual place is its last resort).

In a checkout of the generator, `npm ci` in the checkout installs puppeteer
and minimist (`package.json`), then `npx puppeteer browsers install chrome`.

### Your talk as a PDF

Once `lhtml-site doctor` says *PDF export: ready*, in the `configure.yaml`
of the talk, replace the line `theme: 'slides'` with:

```yaml
theme: 'slides-pdf'
```

and build, in the directory of the talk:

```bash
lhtml-site
```

It writes `slides.pdf`, and `images/` with an image of each slide, next to
`configure.yaml` (a few seconds for a few slides). With this theme the HTML
of the slides is only a step towards the PDF, and is not kept; put
`theme: 'slides'` back to work on the slides in the browser. To get both at
each build, the slides in the browser and the PDF, declare two targets:
[Decks and targets](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#decks-and-targets).

### From a checkout

A clone, or a submodule of a project:

```bash
git clone https://github.com/drohmer/lhtml-site.git
cd lhtml-site
pip install -r requirements.txt
python generate.py ...            # the same as lhtml-site ...
```

`generate.py` at the root of the repository runs the generator of the
checkout (its code is in `src/lhtml_site/`), so the projects that include it
as a submodule call `python <submodule>/generate.py` as before, and keep
naming its files as `<submodule>/themes/slides/` or
`<submodule>/plugins/pre_include.py` (they are found in `src/lhtml_site/`).
`pip install -e .` in a checkout installs the command from it. Runtime and
transitive dependencies are pinned in `requirements-lock.txt`;
`requirements.txt` applies these constraints. `npm ci` installs the locked
Node dependencies.

The checkout also holds a complete demo, a course website with its videos,
in `src/lhtml_site/example/` (not installed by pip: too heavy). To build it:

```bash
mkdir demo
cp -r src/lhtml_site/example demo/src
python generate.py init demo
cd demo
python ../generate.py --serve --watch
```

**Systems**: Linux, macOS and Windows. The tests run on Linux in CI and on
macOS in development; `tests/windows.sh <ssh host>` runs them on a Windows
machine (Windows 11, Python 3.14: they pass, and the example site built
there is identical to the one built on macOS). On Windows, `py -3` is the
reliable launcher: another program may put its own `python` first in the
`PATH`.

## Documentation

- [Reference](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md)
  (`src/lhtml_site/docs/reference.md`): the
  [command line](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#cli-options),
  the [preview server](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#local-preview)
  and the comments on the render,
  the [configuration](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#configuration),
  [decks and targets](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#decks-and-targets),
  [Markdown pages](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#markdown-pages),
  [template variables](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#template-variables),
  the [order of the slides](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#deck-order-of-the-slides),
  [themes](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#theme-what-it-declares-about-the-build),
  the [design](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#design-tokens-macros-and-layouts)
  (tokens, macros, layouts), [credits and figures in code](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#credits-origin-of-the-slides-figures-in-code),
  [plugins](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#plugins),
  the [layout report](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#layout-report-llm-assisted-slide-layout),
  [error reporting](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#error-reporting),
  and [migrating from version 2](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/reference.md#migrating-from-the-previous-layout).
- [Writing slides with an AI agent](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/agents.md):
  the procedure an agent follows (each build copies it into `.structure/agents.md`).
- [Development](https://github.com/drohmer/lhtml-site/blob/main/src/lhtml_site/docs/development.md):
  the layout of the repository, and the tests.

## License

MIT
