# encoding: utf-8
#  This file is part of ansi2html
#  Convert ANSI (terminal) colours and attributes to HTML
#  Copyright (C) 2012  Ralph Bean <rbean@redhat.com>
#  Copyright (C) 2013  Sebastian Pipping <sebastian@pipping.org>
#
#  Inspired by and developed off of the work by pixelbeat and blackjack.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see
#  <http://www.gnu.org/licenses/>.

import io
import optparse
import re
import sys

import pkg_resources

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict

from ansi2html.style import SCHEME, get_styles

ANSI_FULL_RESET = 0
ANSI_INTENSITY_INCREASED = 1
ANSI_INTENSITY_REDUCED = 2
ANSI_INTENSITY_NORMAL = 22
ANSI_STYLE_ITALIC = 3
ANSI_STYLE_NORMAL = 23
ANSI_BLINK_SLOW = 5
ANSI_BLINK_FAST = 6
ANSI_BLINK_OFF = 25
ANSI_UNDERLINE_ON = 4
ANSI_UNDERLINE_OFF = 24
ANSI_CROSSED_OUT_ON = 9
ANSI_CROSSED_OUT_OFF = 29
ANSI_VISIBILITY_ON = 28
ANSI_VISIBILITY_OFF = 8
ANSI_FOREGROUND_CUSTOM_MIN = 30
ANSI_FOREGROUND_CUSTOM_MAX = 37
ANSI_FOREGROUND_256 = 38
ANSI_FOREGROUND_DEFAULT = 39
ANSI_BACKGROUND_CUSTOM_MIN = 40
ANSI_BACKGROUND_CUSTOM_MAX = 47
ANSI_BACKGROUND_256 = 48
ANSI_BACKGROUND_DEFAULT = 49
ANSI_NEGATIVE_ON = 7
ANSI_NEGATIVE_OFF = 27
ANSI_FOREGROUND_HIGH_INTENSITY_MIN = 90
ANSI_FOREGROUND_HIGH_INTENSITY_MAX = 97
ANSI_BACKGROUND_HIGH_INTENSITY_MIN = 100
ANSI_BACKGROUND_HIGH_INTENSITY_MAX = 107

VT100_BOX_CODES = {
    "0x71": "─",
    "0x74": "├",
    "0x75": "┤",
    "0x76": "┴",
    "0x77": "┬",
    "0x78": "│",
    "0x6a": "┘",
    "0x6b": "┐",
    "0x6c": "┌",
    "0x6d": "└",
    "0x6e": "┼",
}

# http://stackoverflow.com/a/15190498
_latex_template = """\\documentclass{scrartcl}
\\usepackage[utf8]{inputenc}
\\usepackage{fancyvrb}
\\usepackage[usenames,dvipsnames]{xcolor}
%% \\definecolor{red-sd}{HTML}{7ed2d2}

\\title{%(title)s}

\\fvset{commandchars=\\\\\\{\\}}

\\begin{document}

\\begin{Verbatim}
%(content)s
\\end{Verbatim}
\\end{document}
"""

_html_template = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=%(output_encoding)s">
<title>%(title)s</title>
<style type="text/css">\n%(style)s\n</style>
</head>
<body class="body_foreground body_background" style="font-size: %(font_size)s;" >
<pre class="ansi2html-content">
%(content)s
</pre>
</body>

</html>
"""


class _State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.intensity = ANSI_INTENSITY_NORMAL
        self.style = ANSI_STYLE_NORMAL
        self.blink = ANSI_BLINK_OFF
        self.underline = ANSI_UNDERLINE_OFF
        self.crossedout = ANSI_CROSSED_OUT_OFF
        self.visibility = ANSI_VISIBILITY_ON
        self.foreground = (ANSI_FOREGROUND_DEFAULT, None)
        self.background = (ANSI_BACKGROUND_DEFAULT, None)
        self.negative = ANSI_NEGATIVE_OFF

    def adjust(self, ansi_code, parameter=None):
        if ansi_code in (
            ANSI_INTENSITY_INCREASED,
            ANSI_INTENSITY_REDUCED,
            ANSI_INTENSITY_NORMAL,
        ):
            self.intensity = ansi_code
        elif ansi_code in (ANSI_STYLE_ITALIC, ANSI_STYLE_NORMAL):
            self.style = ansi_code
        elif ansi_code in (ANSI_BLINK_SLOW, ANSI_BLINK_FAST, ANSI_BLINK_OFF):
            self.blink = ansi_code
        elif ansi_code in (ANSI_UNDERLINE_ON, ANSI_UNDERLINE_OFF):
            self.underline = ansi_code
        elif ansi_code in (ANSI_CROSSED_OUT_ON, ANSI_CROSSED_OUT_OFF):
            self.crossedout = ansi_code
        elif ansi_code in (ANSI_VISIBILITY_ON, ANSI_VISIBILITY_OFF):
            self.visibility = ansi_code
        elif ANSI_FOREGROUND_CUSTOM_MIN <= ansi_code <= ANSI_FOREGROUND_CUSTOM_MAX:
            self.foreground = (ansi_code, None)
        elif (
            ANSI_FOREGROUND_HIGH_INTENSITY_MIN
            <= ansi_code
            <= ANSI_FOREGROUND_HIGH_INTENSITY_MAX
        ):
            self.foreground = (ansi_code, None)
        elif ansi_code == ANSI_FOREGROUND_256:
            self.foreground = (ansi_code, parameter)
        elif ansi_code == ANSI_FOREGROUND_DEFAULT:
            self.foreground = (ansi_code, None)
        elif ANSI_BACKGROUND_CUSTOM_MIN <= ansi_code <= ANSI_BACKGROUND_CUSTOM_MAX:
            self.background = (ansi_code, None)
        elif (
            ANSI_BACKGROUND_HIGH_INTENSITY_MIN
            <= ansi_code
            <= ANSI_BACKGROUND_HIGH_INTENSITY_MAX
        ):
            self.background = (ansi_code, None)
        elif ansi_code == ANSI_BACKGROUND_256:
            self.background = (ansi_code, parameter)
        elif ansi_code == ANSI_BACKGROUND_DEFAULT:
            self.background = (ansi_code, None)
        elif ansi_code in (ANSI_NEGATIVE_ON, ANSI_NEGATIVE_OFF):
            self.negative = ansi_code

    def to_css_classes(self):
        css_classes = []

        def append_unless_default(output, value, default):
            if value != default:
                css_class = "ansi%d" % value
                output.append(css_class)

        def append_color_unless_default(
            output, color, default, negative, neg_css_class
        ):
            value, parameter = color
            if value != default:
                prefix = "inv" if negative else "ansi"
                css_class_index = (
                    str(value) if (parameter is None) else "%d-%d" % (value, parameter)
                )
                output.append(prefix + css_class_index)
            elif negative:
                output.append(neg_css_class)

        append_unless_default(css_classes, self.intensity, ANSI_INTENSITY_NORMAL)
        append_unless_default(css_classes, self.style, ANSI_STYLE_NORMAL)
        append_unless_default(css_classes, self.blink, ANSI_BLINK_OFF)
        append_unless_default(css_classes, self.underline, ANSI_UNDERLINE_OFF)
        append_unless_default(css_classes, self.crossedout, ANSI_CROSSED_OUT_OFF)
        append_unless_default(css_classes, self.visibility, ANSI_VISIBILITY_ON)

        flip_fore_and_background = self.negative == ANSI_NEGATIVE_ON
        append_color_unless_default(
            css_classes,
            self.foreground,
            ANSI_FOREGROUND_DEFAULT,
            flip_fore_and_background,
            "inv_background",
        )
        append_color_unless_default(
            css_classes,
            self.background,
            ANSI_BACKGROUND_DEFAULT,
            flip_fore_and_background,
            "inv_foreground",
        )

        return css_classes


def linkify(line, latex_mode):
    url_matcher = re.compile(
        r"(((((https?|ftps?|gopher|telnet|nntp)://)|"
        r"(mailto:|news:))(%[0-9A-Fa-f]{2}|[-()_.!~*"
        r"\';/?:@&=+$,A-Za-z0-9])+)([).!\';/?:,][\s])?)"
    )
    if latex_mode:
        return url_matcher.sub(r"\\url{\1}", line)
    return url_matcher.sub(r'<a href="\1">\1</a>', line)


def map_vt100_box_code(char):
    char_hex = hex(ord(char))
    return VT100_BOX_CODES[char_hex] if char_hex in VT100_BOX_CODES else char


def _needs_extra_newline(text):
    if not text or text.endswith("\n"):
        return False
    return True


class CursorMoveUp:
    pass


class Ansi2HTMLConverter:
    """Convert Ansi color codes to CSS+HTML

    Example:
    
    >>> conv = Ansi2HTMLConverter()
    >>> ansi = " ".join(sys.stdin.readlines())
    >>> html = conv.convert(ansi)
    """

    def __init__(
        self,
        latex=False,
        inline=False,
        dark_bg=True,
        line_wrap=True,
        font_size="normal",
        linkify=False,
        escaped=True,
        markup_lines=False,
        output_encoding="utf-8",
        scheme="ansi2html",
        title="",
    ):

        self.latex = latex
        self.inline = inline
        self.dark_bg = dark_bg
        self.line_wrap = line_wrap
        self.font_size = font_size
        self.linkify = linkify
        self.escaped = escaped
        self.markup_lines = markup_lines
        self.output_encoding = output_encoding
        self.scheme = scheme
        self.title = title
        self._attrs = None

        if inline:
            self.styles = dict(
                [
                    (item.klass.strip("."), item)
                    for item in get_styles(self.dark_bg, self.line_wrap, self.scheme)
                ]
            )

        self.vt100_box_codes_prog = re.compile("\033\\(([B0])")
        self.ansi_codes_prog = re.compile("\033\\[" "([\\d;]*)" "([a-zA-z])")

    def apply_regex(self, ansi):
        styles_used = set()
        parts = self._apply_regex(ansi, styles_used)
        parts = self._collapse_cursor(parts)
        parts = list(parts)

        if self.linkify:
            parts = [linkify(part, self.latex) for part in parts]

        combined = "".join(parts)

        if self.markup_lines and not self.latex:
            combined = "\n".join(
                [
                    """<span id="line-%i">%s</span>""" % (i, line)
                    for i, line in enumerate(combined.split("\n"))
                ]
            )

        return combined, styles_used

    def _apply_regex(self, ansi, styles_used):
        if self.escaped:
            if (
                self.latex
            ):  # Known Perl function which does this: https://tex.stackexchange.com/questions/34580/escape-character-in-latex/119383#119383
                specials = OrderedDict([])
            else:
                specials = OrderedDict(
                    [
                        ("&", "&amp;"),
                        ("<", "&lt;"),
                        (">", "&gt;"),
                    ]
                )
            for pattern, special in specials.items():
                ansi = ansi.replace(pattern, special)

        def _vt100_box_drawing():
            last_end = 0  # the index of the last end of a code we've seen
            box_drawing_mode = False
            for match in self.vt100_box_codes_prog.finditer(ansi):
                trailer = ansi[last_end : match.start()]
                if box_drawing_mode:
                    for char in trailer:
                        yield map_vt100_box_code(char)
                else:
                    yield trailer
                last_end = match.end()
                box_drawing_mode = match.groups()[0] == "0"
            yield ansi[last_end:]

        ansi = "".join(_vt100_box_drawing())

        state = _State()
        inside_span = False
        last_end = 0  # the index of the last end of a code we've seen
        for match in self.ansi_codes_prog.finditer(ansi):
            yield ansi[last_end : match.start()]
            last_end = match.end()

            params, command = match.groups()

            if command not in "mMA":
                continue

            # Special cursor-moving code.  The only supported one.
            if command == "A":
                yield CursorMoveUp
                continue

            try:
                params = list(map(int, params.split(";")))
            except ValueError:
                params = [ANSI_FULL_RESET]

            # Find latest reset marker
            last_null_index = None
            skip_after_index = -1
            for i, v in enumerate(params):
                if i <= skip_after_index:
                    continue

                if v == ANSI_FULL_RESET:
                    last_null_index = i
                elif v in (ANSI_FOREGROUND_256, ANSI_BACKGROUND_256):
                    skip_after_index = i + 2

            # Process reset marker, drop everything before
            if last_null_index is not None:
                params = params[last_null_index + 1 :]
                if inside_span:
                    inside_span = False
                    if self.latex:
                        yield "}"
                    else:
                        yield "</span>"
                state.reset()

                if not params:
                    continue

            # Turn codes into CSS classes
            skip_after_index = -1
            for i, v in enumerate(params):
                if i <= skip_after_index:
                    continue

                if v in (ANSI_FOREGROUND_256, ANSI_BACKGROUND_256):
                    try:
                        parameter = params[i + 2]
                    except IndexError:
                        continue
                    skip_after_index = i + 2
                else:
                    parameter = None
                state.adjust(v, parameter=parameter)

            if inside_span:
                if self.latex:
                    yield "}"
                else:
                    yield "</span>"
                inside_span = False

            css_classes = state.to_css_classes()
            if not css_classes:
                continue
            styles_used.update(css_classes)

            if self.inline:
                if self.latex:
                    style = [
                        self.styles[klass].kwl[0][1]
                        for klass in css_classes
                        if self.styles[klass].kwl[0][0] == "color"
                    ]
                    yield "\\textcolor[HTML]{%s}{" % style[0]
                else:
                    style = [
                        self.styles[klass].kw
                        for klass in css_classes
                        if klass in self.styles
                    ]
                    yield '<span style="%s">' % "; ".join(style)
            else:
                if self.latex:
                    yield "\\textcolor{%s}{" % " ".join(css_classes)
                else:
                    yield '<span class="%s">' % " ".join(css_classes)
            inside_span = True

        yield ansi[last_end:]
        if inside_span:
            if self.latex:
                yield "}"
            else:
                yield "</span>"
            inside_span = False

    def _collapse_cursor(self, parts):
        """ Act on any CursorMoveUp commands by deleting preceding tokens """

        final_parts = []
        for part in parts:

            # Throw out empty string tokens ("")
            if not part:
                continue

            # Go back, deleting every token in the last 'line'
            if part == CursorMoveUp:
                if final_parts:
                    final_parts.pop()

                while final_parts and "\n" not in final_parts[-1]:
                    final_parts.pop()

                continue

            # Otherwise, just pass this token forward
            final_parts.append(part)

        return final_parts

    def prepare(self, ansi="", ensure_trailing_newline=False):
        """ Load the contents of 'ansi' into this object """

        body, styles = self.apply_regex(ansi)

        if ensure_trailing_newline and _needs_extra_newline(body):
            body += "\n"

        self._attrs = {
            "dark_bg": self.dark_bg,
            "line_wrap": self.line_wrap,
            "font_size": self.font_size,
            "body": body,
            "styles": styles,
        }

        return self._attrs

    def attrs(self):
        """ Prepare attributes for the template """
        if not self._attrs:
            raise Exception("Method .prepare not yet called.")
        return self._attrs

    def convert(self, ansi, full=True, ensure_trailing_newline=False):
        attrs = self.prepare(ansi, ensure_trailing_newline=ensure_trailing_newline)
        if not full:
            return attrs["body"]
        if self.latex:
            _template = _latex_template
        else:
            _template = _html_template
        all_styles = get_styles(self.dark_bg, self.line_wrap, self.scheme)
        backgrounds = all_styles[:6]
        used_styles = filter(
            lambda e: e.klass.lstrip(".") in attrs["styles"], all_styles
        )

        return _template % {
            "style": "\n".join(list(map(str, backgrounds + list(used_styles)))),
            "title": self.title,
            "font_size": self.font_size,
            "content": attrs["body"],
            "output_encoding": self.output_encoding,
        }

    def produce_headers(self):
        return '<style type="text/css">\n%(style)s\n</style>\n' % {
            "style": "\n".join(
                map(str, get_styles(self.dark_bg, self.line_wrap, self.scheme))
            )
        }


def main():
    """
    $ ls --color=always | ansi2html > directories.html
    $ sudo tail /var/log/messages | ccze -A | ansi2html > logs.html
    $ task burndown | ansi2html > burndown.html
    """

    scheme_names = sorted(SCHEME.keys())
    version_str = pkg_resources.get_distribution("ansi2html").version
    parser = optparse.OptionParser(
        usage=main.__doc__, version="%%prog %s" % version_str
    )
    parser.add_option(
        "-p",
        "--partial",
        dest="partial",
        default=False,
        action="store_true",
        help="Process lines as them come in.  No headers are produced.",
    )
    parser.add_option(
        "-L",
        "--latex",
        dest="latex",
        default=False,
        action="store_true",
        help="Export as LaTeX instead of HTML.",
    )
    parser.add_option(
        "-i",
        "--inline",
        dest="inline",
        default=False,
        action="store_true",
        help="Inline style without headers or template.",
    )
    parser.add_option(
        "-H",
        "--headers",
        dest="headers",
        default=False,
        action="store_true",
        help="Just produce the <style> tag.",
    )
    parser.add_option(
        "-f",
        "--font-size",
        dest="font_size",
        metavar="SIZE",
        default="normal",
        help="Set the global font size in the output.",
    )
    parser.add_option(
        "-l",
        "--light-background",
        dest="light_background",
        default=False,
        action="store_true",
        help="Set output to 'light background' mode.",
    )
    parser.add_option(
        "-W",
        "--no-line-wrap",
        dest="no_line_wrap",
        default=False,
        action="store_true",
        help="Disable line wrapping.",
    )
    parser.add_option(
        "-a",
        "--linkify",
        dest="linkify",
        default=False,
        action="store_true",
        help="Transform URLs into <a> links.",
    )
    parser.add_option(
        "-u",
        "--unescape",
        dest="escaped",
        default=True,
        action="store_false",
        help="Do not escape XML tags found in the input.",
    )
    parser.add_option(
        "-m",
        "--markup-lines",
        dest="markup_lines",
        default=False,
        action="store_true",
        help="Surround lines with <span id='line-n'>..</span>.",
    )
    parser.add_option(
        "--input-encoding",
        dest="input_encoding",
        metavar="ENCODING",
        default="utf-8",
        help="Specify input encoding",
    )
    parser.add_option(
        "--output-encoding",
        dest="output_encoding",
        metavar="ENCODING",
        default="utf-8",
        help="Specify output encoding",
    )
    parser.add_option(
        "-s",
        "--scheme",
        dest="scheme",
        metavar="SCHEME",
        default="ansi2html",
        choices=scheme_names,
        help=(
            "Specify color palette scheme. Default: %%default. Choices: %s"
            % scheme_names
        ),
    )
    parser.add_option(
        "-t", "--title", dest="output_title", default="", help="Specify output title"
    )

    opts, args = parser.parse_args()

    conv = Ansi2HTMLConverter(
        latex=opts.latex,
        inline=opts.inline,
        dark_bg=not opts.light_background,
        line_wrap=not opts.no_line_wrap,
        font_size=opts.font_size,
        linkify=opts.linkify,
        escaped=opts.escaped,
        markup_lines=opts.markup_lines,
        output_encoding=opts.output_encoding,
        scheme=opts.scheme,
        title=opts.output_title,
    )

    try:
        sys.stdin = io.TextIOWrapper(sys.stdin.detach(), opts.input_encoding, "replace")
    except io.UnsupportedOperation:
        # This only fails in the test suite...
        pass

    def _read(input_bytes):
        return input_bytes

    def _print(output_unicode, end="\n"):
        if hasattr(sys.stdout, "buffer"):
            output_bytes = (output_unicode + end).encode(opts.output_encoding)
            sys.stdout.buffer.write(output_bytes)
        else:
            sys.stdout.write(output_unicode + end)

    # Produce only the headers and quit
    if opts.headers:
        _print(conv.produce_headers(), end="")
        return

    full = not bool(opts.partial or opts.inline)
    output = conv.convert(
        "".join(sys.stdin.readlines()), full=full, ensure_trailing_newline=True
    )
    _print(output, end="")
