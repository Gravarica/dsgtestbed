# Sample data

The documents are passages from five public-domain books of Project Gutenberg, https://www.gutenberg.org:
*Frankenstein* (84), *A Tale of Two Cities* (98), *Pride and Prejudice* (1342), *The Adventures of Sherlock
Holmes* (1661) and *Moby Dick* (2701). The texts are in the public domain in the United States; the Project
Gutenberg header and footer, which carry the trademark licence, are removed.

`prepare.sh` downloads the five books into `fetched/books/` and `split_documents.py` cuts each one into
passages of about 8000 characters at paragraph boundaries, keeping the first 40 of every book, so
`fetched/documents/` holds 200 documents. They are too many files for git, so nothing but this file lives in
`data/`.
