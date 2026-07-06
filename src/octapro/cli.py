"""CLI entrypoint — `octaproctl` binary."""

import sys
from pathlib import Path
from typing import Annotated

import typer

from octapro import __version__

app = typer.Typer(
    name="octaproctl",
    help="Read-only USB HID CLI for the Audiobeat OctaPro 8.2 / SP601 Car DSP Amplifier.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
read_app = typer.Typer(help="Read live device state.", no_args_is_help=True)
write_app = typer.Typer(
    help="Write DSP parameters. **Dry-run by default** — add `--commit` to apply.",
    no_args_is_help=True,
)
dump_app = typer.Typer(
    help="Hex-dump raw channel blocks from the live device.", no_args_is_help=True
)

app.add_typer(read_app, name="read")
app.add_typer(write_app, name="write")
app.add_typer(dump_app, name="dump")

# ---------------------------------------------------------------------------
# Shared option types
# ---------------------------------------------------------------------------

_Verbose = Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug output.")]
_Quiet = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress INFO messages.")]
_LogFile = Annotated[
    Path | None, typer.Option("--log-file", help="Research JSONL log path (appended).")
]
_NoKA = Annotated[
    bool, typer.Option("--no-keepalive", help="Skip keepalive thread (for quick one-shot reads).")
]


def _setup(verbose: bool, quiet: bool, log_file: Path | None) -> None:
    from octapro.logging import setup_logging
    setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"octaproctl {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Root callback (--version only)
# ---------------------------------------------------------------------------

@app.callback()
def _root(
    _version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=_version_cb, is_eager=True, help="Show version and exit."
        ),
    ] = None,
) -> None:
    pass


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@app.command()
def info(
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
    no_keepalive: _NoKA = False,
) -> None:
    """Connect to the device and print firmware + device info."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.info import run_info
    sys.exit(run_info(no_keepalive=no_keepalive))


# ---------------------------------------------------------------------------
# parse-dat
# ---------------------------------------------------------------------------

@app.command(name="parse-dat")
def parse_dat(
    path: Annotated[Path, typer.Argument(help="Path to a .dat preset file (US002 format).")],
    channel: Annotated[
        int | None,
        typer.Option("--channel", "-c", min=1, max=10, help="Show only channel N (1-10)."),
    ] = None,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Parse a .dat preset file **offline** — no device required."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.dat import run_parse_dat
    sys.exit(run_parse_dat(path=path, channel=channel))


# ---------------------------------------------------------------------------
# decode-pcap
# ---------------------------------------------------------------------------

@app.command(name="decode-pcap")
def decode_pcap(
    pcapng: Annotated[Path, typer.Argument(help="Path to .pcapng capture file.")],
    out: Annotated[
        Path | None, typer.Option("--out", help="Write decoded events to a JSONL file.")
    ] = None,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Decode a USB capture offline — requires **tshark** in PATH."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.decode_pcap import run_decode_pcap
    sys.exit(run_decode_pcap(pcapng=pcapng, out=out))


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

@app.command()
def probe(
    hex_bytes: Annotated[
        str, typer.Argument(help="256-byte OUT packet as a hex string (spaces OK).")
    ],
    commit: Annotated[
        bool,
        typer.Option("--commit", help="Actually transmit — without this, only prints the packet."),
    ] = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Send a raw hand-crafted packet. Dry-run without `--commit`."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.probe import run_probe
    sys.exit(run_probe(hex_bytes=hex_bytes, commit=commit))


# ---------------------------------------------------------------------------
# monitor
# ---------------------------------------------------------------------------

@app.command()
def monitor(
    interval: Annotated[
        float, typer.Option("--interval", min=0.1, help="Poll interval in seconds.")
    ] = 0.5,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Live-poll all channels and highlight changes (Ctrl-C to stop)."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.monitor import run_monitor
    sys.exit(run_monitor(interval=interval))


# ---------------------------------------------------------------------------
# read sub-app
# ---------------------------------------------------------------------------

@read_app.command(name="channel")
def read_channel(
    channel: Annotated[str, typer.Argument(help="Channel number 1-10 or 'all'.")],
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Read and decode one or all DSP channels."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.read import run_read_channel
    sys.exit(run_read_channel(channel=channel, no_keepalive=no_keepalive))


@read_app.command(name="master")
def read_master(
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Read the master (CH0) block."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.read import run_read_master
    sys.exit(run_read_master(no_keepalive=no_keepalive))


@read_app.command(name="knob-vol")
def read_knob_vol(
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Read the remote-knob volume (knob-vol, from the keepalive response).

    Not the software "Main" fader — that is the master (CH0), see `read master`.
    """
    _setup(verbose, quiet, log_file)
    from octapro.commands.read import run_read_knob_vol
    sys.exit(run_read_knob_vol(no_keepalive=no_keepalive))


# ---------------------------------------------------------------------------
# dump sub-app
# ---------------------------------------------------------------------------

@dump_app.command(name="channel")
def dump_channel(
    channel: Annotated[int, typer.Argument(min=1, max=10, help="Channel number 1-10.")],
    annotate: Annotated[
        bool, typer.Option("--annotate", help="Show per-byte field labels.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Hex-dump a raw channel block from the live device."""
    _setup(verbose, quiet, log_file)
    from octapro.commands.dump import run_dump_channel
    sys.exit(run_dump_channel(channel=channel, annotate=annotate, no_keepalive=no_keepalive))


# ---------------------------------------------------------------------------
# write sub-app
# ---------------------------------------------------------------------------

def _write_crossover_cmd(
    kind: str, channel: int, freq: float, slope_db: int, filter_type: str,
    commit: bool, verbose: bool, quiet: bool, log_file: Path | None, no_keepalive: bool,
) -> None:
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_crossover
    sys.exit(run_write_crossover(
        kind=kind, channel=channel, freq=freq, slope_db=slope_db, filter_type=filter_type,
        commit=commit, no_keepalive=no_keepalive,
    ))


@write_app.command(name="hpf")
def write_hpf(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    freq: Annotated[float, typer.Option("--freq", help="Cutoff frequency in Hz.")],
    slope_db: Annotated[
        int, typer.Option("--slope-db", help="Slope in dB/oct (6, 12, 18, 24, 30, 36, 42, 48).")
    ] = 36,
    filter_type: Annotated[
        str, typer.Option("--type", help="Filter type: bessel, butterworth, or lr.")
    ] = "bessel",
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a channel's high-pass filter (freq, slope, type). **Dry-run unless `--commit`.**"""
    _write_crossover_cmd(
        "hpf", channel, freq, slope_db, filter_type, commit, verbose, quiet, log_file, no_keepalive
    )


@write_app.command(name="lpf")
def write_lpf(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    freq: Annotated[float, typer.Option("--freq", help="Cutoff frequency in Hz.")],
    slope_db: Annotated[
        int, typer.Option("--slope-db", help="Slope in dB/oct (6, 12, 18, 24, 30, 36, 42, 48).")
    ] = 36,
    filter_type: Annotated[
        str, typer.Option("--type", help="Filter type: bessel, butterworth, or lr.")
    ] = "bessel",
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a channel's low-pass filter (freq, slope, type). **Dry-run unless `--commit`.**"""
    _write_crossover_cmd(
        "lpf", channel, freq, slope_db, filter_type, commit, verbose, quiet, log_file, no_keepalive
    )


@write_app.command(name="gain")
def write_gain(
    channel: Annotated[
        int,
        typer.Option(
            "--channel", "-c", min=1, max=10,
            help="Channel 1-10 output fader. For the master fader use `write master`.",
        ),
    ],
    db: Annotated[float, typer.Option("--db", help="Fader level in dB.")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a channel's output fader/gain in dB (CMD 0x08). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_gain
    sys.exit(run_write_gain(channel=channel, db=db, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="master")
def write_master(
    db: Annotated[float, typer.Option("--db", help="Master volume in dB (+6..-60).")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set master (Main) volume in dB. **Dry-run unless `--commit` is given.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_master
    sys.exit(run_write_master(db=db, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="mute")
def write_mute(
    channel: Annotated[
        int,
        typer.Option(
            "--channel", "-c", min=0, max=10,
            help="Channel 1-10, or 0 = master/Main (only master is live-verified).",
        ),
    ] = 0,
    on: Annotated[bool, typer.Option("--on/--off", help="Mute (--on) or unmute (--off).")] = True,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Mute or unmute a channel (master by default). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_mute
    sys.exit(run_write_mute(channel=channel, mute=on, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="solo")
def write_solo(
    channel: Annotated[
        int,
        typer.Option("--channel", "-c", min=1, max=10, help="Channel to solo (1-10)."),
    ],
    on: Annotated[
        bool, typer.Option("--on/--off", help="Solo (--on) or un-solo (--off).")
    ] = True,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Solo a channel by muting all others (client-side macro, like the vendor
    app — there is no device solo command). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_solo
    sys.exit(run_write_solo(channel=channel, solo=on, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="source-high")
def write_source_high(
    to: Annotated[
        str, typer.Option("--to", "-t", help="High-priority source: bt or usb-disk.")
    ],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Select the HIGH (auto-switch) input source: bt or usb-disk. **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_source
    sys.exit(run_write_source(tier="high", source=to, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="source-low")
def write_source_low(
    to: Annotated[
        str,
        typer.Option(
            "--to", "-t", help="Normal-priority source: high-level, low-level, opt, or usb-audio."
        ),
    ],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Select the LOW (normal) input source: high-level/low-level/opt/usb-audio.
    **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_source
    sys.exit(run_write_source(tier="low", source=to, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="speaker-type")
def write_speaker_type(
    channel: Annotated[
        int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")
    ],
    speaker_type: Annotated[
        str,
        typer.Option(
            "--type", "-t", help="Speaker type: hf, mf, lf, mhf, mlf, or ff (menu order 1-6)."
        ),
    ],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a channel's speaker type (HF/MF/LF/MHF/MLF/FF). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_speaker_type
    sys.exit(
        run_write_speaker_type(
            channel=channel, speaker_type=speaker_type, commit=commit, no_keepalive=no_keepalive
        )
    )


@write_app.command(name="eq")
def write_eq(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    band: Annotated[
        int, typer.Option("--band", "-b", min=1, max=31, help="EQ band 1-31 (1=20 Hz … 31=20 kHz).")
    ],
    db: Annotated[float, typer.Option("--db", help="Band gain in dB.")] = 0.0,
    q: Annotated[float, typer.Option("--q", help="Q factor (default 1.0).")] = 1.0,
    freq: Annotated[
        float | None,
        typer.Option("--freq", help="Center frequency in Hz (default = band's standard center)."),
    ] = None,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a 31-band EQ band's gain, freq, and Q (CMD 0x0a — one atomic write).

    **All three are written together**; unspecified options use defaults, so
    to change one against a live device, pass the band's current values for
    the others. **Dry-run unless `--commit`.**
    """
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_eq
    sys.exit(
        run_write_eq(
            channel=channel, band=band, db=db, q=q, freq=freq,
            commit=commit, no_keepalive=no_keepalive,
        )
    )


@write_app.command(name="delay")
def write_delay(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    ms: Annotated[float, typer.Option("--ms", help="Time-alignment delay in milliseconds.")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set a channel's time-alignment delay in ms (CMD 0x08). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_delay
    sys.exit(run_write_delay(channel=channel, ms=ms, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="eq-pass")
def write_eq_pass(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    bypass: Annotated[
        bool, typer.Option("--on/--off", help="Bypass the channel EQ (--on) or engage it (--off).")
    ] = True,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Bypass/engage a channel's EQ (CMD 0x05 selector 0x07). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_eq_pass
    sys.exit(
        run_write_eq_pass(channel=channel, bypass=bypass, commit=commit, no_keepalive=no_keepalive)
    )


@write_app.command(name="eq-reset")
def write_eq_reset(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Reset (flatten) a channel's EQ (CMD 0x05, the RST button). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_eq_reset
    sys.exit(run_write_eq_reset(channel=channel, commit=commit, no_keepalive=no_keepalive))


@write_app.command(name="phase")
def write_phase(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    invert: Annotated[
        bool, typer.Option("--invert/--normal", help="180° invert (--invert) or 0° (--normal).")
    ] = True,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set channel phase (0° / 180°). **Dry-run unless `--commit` is given.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_phase
    sys.exit(
        run_write_phase(channel=channel, invert=invert, commit=commit, no_keepalive=no_keepalive)
    )


@write_app.command(name="bridge")
def write_bridge(
    on: Annotated[
        bool, typer.Option("--on/--off", help="Bridge CH7+CH8 (--on) or unbridge (--off).")
    ] = True,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Bridge/unbridge CH7+CH8 (the only bridgeable pair). **Dry-run unless `--commit`.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_bridge
    sys.exit(run_write_bridge(bridged=on, commit=commit, no_keepalive=no_keepalive))
