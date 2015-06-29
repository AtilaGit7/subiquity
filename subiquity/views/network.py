# Copyright 2015 Canonical, Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
from urwid import (WidgetWrap, ListBox, Pile, BoxAdapter, Text, Columns)
from subiquity.ui.lists import SimpleList
from subiquity.ui.buttons import confirm_btn, cancel_btn
from subiquity.ui.utils import Padding, Color


log = logging.getLogger('subiquity.networkView')


class NetworkView(WidgetWrap):
    def __init__(self, model, cb):
        self.model = model
        self.cb = cb
        self.items = []
        self.body = [
            Padding.center_79(self._build_model_inputs()),
            Padding.line_break(""),
            Padding.center_79(self._build_additional_options()),
            Padding.line_break(""),
            Padding.center_20(self._build_buttons()),
        ]
        super().__init__(ListBox(self.body))

    def _build_buttons(self):
        buttons = [
            Color.button_secondary(cancel_btn(on_press=self.cancel),
                                   focus_map='button_secondary focus'),
        ]
        return Pile(buttons)

    def _build_model_inputs(self):
        log.info("probing for network devices")
        self.model.probe_network()
        ifaces = self.model.get_interfaces()

        col_1 = []
        for iface in ifaces:
            col_1.append(
                Color.button_primary(confirm_btn(label=iface,
                                                 on_press=self.confirm),
                                     focus_map='button_primary focus'))
        col_1 = BoxAdapter(SimpleList(col_1),
                           height=len(col_1))

        col_2 = []
        for iface in ifaces:
            ifinfo, iface_vendor, iface_model = self.model.get_iface_info(
                iface)
            col_2.append(Text("Address: {}".format(ifinfo.addr)))
            col_2.append(
                Text("{} - {}".format(iface_vendor,
                                      iface_model)))
        col_2 = BoxAdapter(SimpleList(col_2, is_selectable=False),
                           height=len(col_2))

        return Columns([(10, col_1), col_2], 2)

    def _build_additional_options(self):
        opts = []
        for opt in self.model.additional_options:
            opts.append(
                Color.button_secondary(confirm_btn(label=opt,
                                                   on_press=self.confirm),
                                       focus_map='button_secondary focus'))
        return Pile(opts)

    def confirm(self, button):
        return self.cb(button.label)

    def cancel(self, button):
        return self.cb(None)
