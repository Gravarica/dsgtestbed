import sys
from pathlib import Path

DOCUMENTS_PER_BOOK = 40
CHARACTERS_PER_DOCUMENT = 8000
START_MARKER = "*** START OF THE PROJECT GUTENBERG EBOOK"
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK"


def body_of(book: str) -> str:
    after_header = book.split(START_MARKER, 1)[1].split("***", 1)[1]
    return after_header.split(END_MARKER, 1)[0].strip()


def documents_of(body: str):
    paragraphs = [paragraph.strip() for paragraph in body.split("\n\n") if paragraph.strip()]
    document, length = [], 0
    for paragraph in paragraphs:
        document.append(paragraph)
        length += len(paragraph) + 2
        if length >= CHARACTERS_PER_DOCUMENT:
            yield "\n\n".join(document)
            document, length = [], 0
    if document:
        yield "\n\n".join(document)


def split(books_directory: Path, documents_directory: Path) -> None:
    documents_directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for book_file in sorted(books_directory.glob("*.txt")):
        body = body_of(book_file.read_text(encoding="utf-8"))
        documents = list(documents_of(body))[:DOCUMENTS_PER_BOOK]
        if len(documents) < DOCUMENTS_PER_BOOK:
            raise SystemExit(f"{book_file} yields only {len(documents)} documents")
        for number, document in enumerate(documents):
            (documents_directory / f"{book_file.stem}-{number:03d}.txt").write_text(document, encoding="utf-8")
            written += 1
    print(f"{written} documents in {documents_directory}")


if __name__ == "__main__":
    split(Path(sys.argv[1]), Path(sys.argv[2]))
