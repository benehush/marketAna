"""Standalone document readers."""

from data_proccessing.readers.base import Reader, read_path
from data_proccessing.readers.html_reader import read_html
from data_proccessing.readers.image_reader import read_image
from data_proccessing.readers.pdf_reader import read_pdf
from data_proccessing.readers.text_reader import read_text

__all__ = ["Reader", "read_path", "read_html", "read_image", "read_pdf", "read_text"]
