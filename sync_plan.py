#!/usr/bin/env python3
"""Works out how to make the local video folders match a source, either USB or Nextcloud"""


def make_plan(source, local):
    """
    Plan a sync, without changing anything.
    Args:
        source: {folder name: set of lowercase video file names} on the source
        local: the same, for the local folders
    Returns:
        dict: 'update' and 'copy' lists of folder names, 'rename' list of
        (old name, new name), and 'delete' list of local folder names
    """
    # Local folders that are going away. Only these may be renamed, since a folder
    # that's still on the source must stay, even if another one has the same videos.
    leaving = {name: videos for name, videos in sorted(local.items()) if name not in source}
    plan = {'update': [], 'copy': [], 'rename': [], 'delete': []}

    for name, videos in sorted(source.items()):
        if name in local:
            plan['update'].append(name)
            continue
        old_name = next((old for old, old_videos in leaving.items() if videos and old_videos == videos), None)
        if old_name:
            del leaving[old_name]
            plan['rename'].append((old_name, name))
        else:
            plan['copy'].append(name)

    plan['delete'] = sorted(leaving)
    return plan
