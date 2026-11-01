"""Ghostwriting as an MCP server: an agent checks every document before it reads a word of it.

    ghostwriting mcp

An agent that calls check_document first gets the exorcised text instead of the haunted one, so the ghost never
reaches the model at all.
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .cli import documents, row
from .scanner import check

mcp = FastMCP("ghostwriting")


@mcp.tool()
def check_document(path: str) -> dict:
    """Read a PDF or text file the way a person sees it and the way an AI receives it.
    Returns whether it is haunted, every hidden run that talks to an AI (its page, its text, how it was hidden,
    what it asks), other hidden text, and `clean_text`: the document with every hidden word taken out, safe to read.
    Read `clean_text` instead of the original file."""
    return check(Path(path).expanduser())


@mcp.tool()
def check_folder(path: str) -> list[dict]:
    """Check every PDF and text file in a folder (and its subfolders). One row per document, haunted ones first,
    with the first hidden sentence and how it was hidden. Use check_document on a row to get its clean text."""
    rows = [row(f) for f in documents([Path(path).expanduser()])]
    order = {"haunted": 0, "hidden text": 1, "could not read": 2, "clean": 3}
    return sorted(rows, key=lambda r: (order[r["verdict"]], r["file"]))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
