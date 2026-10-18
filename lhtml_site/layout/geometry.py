"""Rectangles and the tree of the blocks, as the layout analysis uses them.

A box of the measurement is a dict {x, y, w, h}; a rectangle is a tuple
(x0, y0, x1, y1), sometimes followed by the type of its ink. A node of the
tree names its parent by id ('parent'), looked up in a dict {id: node}.
"""


def rect(box):
    """(x0, y0, x1, y1) of a box {x, y, w, h}."""
    return box['x'], box['y'], box['x'] + box['w'], box['y'] + box['h']


def area(r):
    """The area of a rectangle (x0, y0, x1, y1, ...)."""
    return (r[2] - r[0]) * (r[3] - r[1])


def ancestors(node, by_id):
    """The ancestors of a node, nearest first."""
    while node.get('parent') in by_id:
        node = by_id[node['parent']]
        yield node


def nearest_ancestor(node, by_id, predicate):
    """The nearest ancestor of a node for which `predicate` holds, or None."""
    return next((a for a in ancestors(node, by_id) if predicate(a)), None)
