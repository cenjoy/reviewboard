from reviewboard.diffviewer.diffutils import (get_diff_files,
                                              get_line_changed_regions,
                                              patch)
        diff_files = get_diff_files(diffset, None, interdiffset)