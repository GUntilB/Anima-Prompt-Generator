# Data sources

The tag dictionary comes from Danbooru. This project is not affiliated with Danbooru.

## data/auto/ (generated files, an updater may overwrite them)

### tags.csv
Columns: `tag`, `category`, `post_count`. Categories: 0 general, 1 artist, 3 copyright (series), 4 character, 5 meta.

It was assembled from two lists:

1. The author's own list, exported from the Danbooru API with a script: tags with at least 1000 posts,
   tags flagged `is_deprecated` skipped, underscores replaced by spaces. Names, categories and post counts
   come from Danbooru. The export missed part of the popular tags and all rarer ones, so it was completed
   with list 2.
2. The dataset **danbooru-tag-csv** by newtextdoc1111 (MIT license):
   <https://huggingface.co/datasets/newtextdoc1111/danbooru-tag-csv>,
   itself created from `itterative/danbooru_wikis_full` and `trojblue/danbooru2025-metadata`.
   Its general, character and copyright tags that were missing from list 1 were added with `tools/merge_tags.py`.
   The dataset has no artist or meta tags. Post counts of the added tags were multiplied by 1.87 (the median
   ratio over the tags both lists share) so that they match the scale of list 1.

### aliases.csv
Pairs `alias,tag`: active Danbooru tag aliases (`/tag_aliases.json`) whose target tag is in `tags.csv`,
exported with the same script.

## data/manual/ (your own edits, never touched by updates)

- `tags.csv`: tags added by hand (same columns as `auto/tags.csv`). Manual entries win over auto entries.
- `aliases.csv`: your own alias rules (`alias,tag`). They are read after `auto/aliases.csv` and win over it.

## Third-party license notice

The part of `data/auto/tags.csv` that comes from danbooru-tag-csv is used under the MIT license.
The dataset page states the license but does not name a copyright holder, so the author's Hugging Face
account name is used in the notice:

```
MIT License

Copyright (c) newtextdoc1111

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
