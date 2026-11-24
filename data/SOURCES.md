# Data sources

The tag dictionary comes from Danbooru. This project is not affiliated with Danbooru.

## data/auto/ (generated files, the updater overwrites them)

Both files are downloaded from the Danbooru API by the Anima Dictionary Updater node (or `tools/update_tags.py`).
The files in this release were downloaded on 24 November 2026 with the default settings: tags with at least
100 posts, tags that Danbooru flags as deprecated included.

### tags.csv
Columns: `tag`, `category`, `post_count`. Categories: 0 general, 1 artist, 3 copyright (series), 4 character, 5 meta.
Names, categories and post counts come from Danbooru (`/tags.json`); underscores are replaced by spaces.

### aliases.csv
Pairs `alias,tag`: active Danbooru tag aliases (`/tag_aliases.json`) whose target tag is in the dictionary.

## data/manual/ (your own edits, never touched by updates)

- `tags.csv`: tags added by hand (same columns as `auto/tags.csv`). Manual entries win over auto entries.
- `aliases.csv`: your own alias rules (`alias,tag`). They are read after `auto/aliases.csv` and win over it.
