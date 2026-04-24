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

@write_app.command(name="hpf")
def write_hpf(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    freq: Annotated[float, typer.Option("--freq", help="Cutoff frequency in Hz.")],
    slope: Annotated[
        int, typer.Option("--slope", help="Slope code byte (0x05=36 dB/oct, 0x03=12 dB/oct).")
    ] = 0x05,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set HPF frequency on a channel. **Dry-run unless `--commit` is given.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_hpf
    sys.exit(run_write_hpf(
        channel=channel, freq=freq, slope=slope, commit=commit, no_keepalive=no_keepalive
    ))


@write_app.command(name="gain")
def write_gain(
    channel: Annotated[int, typer.Option("--channel", "-c", min=1, max=10, help="Channel 1-10.")],
    db: Annotated[float, typer.Option("--db", help="Gain in dB.")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually send — without this, prints the packet only.")
    ] = False,
    no_keepalive: _NoKA = False,
    verbose: _Verbose = False,
    quiet: _Quiet = False,
    log_file: _LogFile = None,
) -> None:
    """Set channel gain in dB. **Dry-run unless `--commit` is given.**"""
    _setup(verbose, quiet, log_file)
    from octapro.commands.write import run_write_gain
    sys.exit(run_write_gain(channel=channel, db=db, commit=commit, no_keepalive=no_keepalive))
