set -e
cd "$(dirname "$0")"
mkdir -p fetched

for book in 84 98 1342 1661 2701; do
  if [ ! -f fetched/books/pg$book.txt ]; then
    mkdir -p fetched/books
    curl -L --fail --silent --show-error -o fetched/books/pg$book.txt \
      "https://www.gutenberg.org/cache/epub/$book/pg$book.txt"
  fi
done

if [ ! -f fetched/documents/pg84-039.txt ]; then
  python3 split_documents.py fetched/books fetched/documents
fi
echo "$(ls fetched/documents/*.txt | wc -l) documents in fetched/documents"
