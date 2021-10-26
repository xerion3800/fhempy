import asyncio
import enum
import functools
import inspect
import json
import typing

from miio.click_common import DeviceGroupMeta

from .. import fhem, utils
from .. import generic


class miio(generic.FhemModule):
    def __init__(self, logger):
        super().__init__(logger)
        self._set_list = {}
        self._device = None
        self._fct_update_tasks = {}
        self._attr_update_functions = ""
        self._attr_list = {
            "update_functions": {
                "default": "status:60,info:600",
                "help": (
                    "Define command which should be executed every X seconds.<br>"
                    "info:600 executes info every 600s<br>Default: status:60,info:600"
                ),
            }
        }
        self.set_attr_config(self._attr_list)
        return

    # FHEM FUNCTION
    async def Define(self, hash, args, argsh):
        await super().Define(hash, args, argsh)
        self.hash = hash
        if len(args) < 6:
            return "Usage: define miiodev fhempy miio <TYPE> <IP> <TOKEN>"
        self._miio_devtype = args[3]
        self._miio_ip = args[4]
        self._miio_token = args[5]

        self._miio_device_class = None
        for device_class in DeviceGroupMeta.device_classes:
            if device_class.get_device_group().name == self._miio_devtype:
                self._miio_device_class = device_class
                break
        if self._miio_device_class is None:
            return f"Device {self._miio_devtype} not found."

        for dev_cmd in self._miio_device_class.get_device_group().commands.keys():
            self._set_list[dev_cmd] = {"function": "set_command", "default": None}
            fct = getattr(self._miio_device_class, dev_cmd)
            sig = inspect.signature(fct)
            if len(list(sig.parameters)) > 1:
                self._set_list[dev_cmd]["args"] = []
                self._set_list[dev_cmd]["help"] = []
                for par in sig.parameters:
                    if sig.parameters[par].name == "self":
                        continue
                    self._set_list[dev_cmd]["args"].append(sig.parameters[par].name)
                    self._set_list[dev_cmd]["help"].append(str(sig.parameters[par]))
                    if len(list(sig.parameters)) == 2:
                        # set options if there is only one parameter
                        annot = sig.parameters[par].annotation
                        if not inspect.isclass(annot):
                            self.logger.error("Annotation is not class: " + str(annot))
                        if inspect.isclass(annot) and issubclass(annot, enum.Enum):
                            self._set_list[dev_cmd]["options"] = ",".join(
                                list(map(lambda x: x.name, annot))
                            )
                        elif inspect.isclass(annot) and issubclass(annot, bool):
                            self._set_list[dev_cmd]["options"] = "on,off"
                self._set_list[dev_cmd]["help"] = "Arguments: " + " ".join(
                    self._set_list[dev_cmd]["help"]
                )

        self.set_set_config(self._set_list)
        self._device = self._miio_device_class(ip=self._miio_ip, token=self._miio_token)
        await fhem.readingsSingleUpdateIfChanged(hash, "state", "active", 1)

    async def set_attr_update_functions(self, hash):
        for task in self._fct_update_tasks.copy():
            self._fct_update_tasks[task].cancel()
            del self._fct_update_tasks[task]

        if self._attr_update_functions != "":
            fct_upd_list = self._attr_update_functions.split(",")
            for fct_upd in fct_upd_list:
                sec = int(fct_upd.split(":")[1])
                fct = fct_upd.split(":")[0]
                self._fct_update_tasks[fct] = self.create_async_task(
                    self.fct_update_loop(fct, sec)
                )

    async def fct_update_loop(self, fct_name, sec):
        while True:
            try:
                await self.send_command(fct_name, None)
                await fhem.readingsSingleUpdateIfChanged(
                    self.hash, "presence", "online", 1
                )
            except Exception:
                self.logger.error(f"Failed to send_command: {fct_name}")
                await fhem.readingsSingleUpdateIfChanged(
                    self.hash, "presence", "offline", 1
                )
            await asyncio.sleep(sec)

    async def set_command(self, hash, params):
        cmd = params["cmd"]
        self.create_async_task(self.send_command(cmd, params))

    def is_number(self, string):
        try:
            float(string)
            return True
        except ValueError:
            return False

    async def send_command(self, fct_name, params):
        fct = getattr(self._device, fct_name)
        sig = inspect.signature(fct)
        args = []
        for par_name in sig.parameters:
            if params[par_name] is None:
                continue
            ann = sig.parameters[par_name].annotation
            if inspect.isclass(ann) and issubclass(ann, enum.Enum):
                args.append(ann[params[par_name]])
            elif inspect.isclass(ann) and issubclass(ann, bool):
                args.append(params[par_name] == "on")
            elif ann == typing.List:
                args.append(json.loads(params[par_name]))
            elif ann == inspect.Signature.empty:
                if self.is_number(params[par_name]):
                    args.append(float(params[par_name]))
                else:
                    args.append(params[par_name])
            else:
                args.append(ann(params[par_name]))
        # call function with arguments
        reply = await utils.run_blocking(functools.partial(fct, *args))
        # handle reply
        if hasattr(reply, "__dict__"):
            await fhem.readingsBeginUpdate(self.hash)
            try:
                st = dict(
                    (x, getattr(reply, x))
                    for x in reply.__class__.__dict__
                    if isinstance(reply.__class__.__dict__[x], property)
                )
                for prop in st:
                    if prop == "raw":
                        continue
                    try:
                        for data_name in st[prop]:
                            await fhem.readingsBulkUpdateIfChanged(
                                self.hash, prop + "_" + data_name, st[prop][data_name]
                            )
                    except Exception:
                        await fhem.readingsBulkUpdateIfChanged(
                            self.hash, prop, st[prop]
                        )
            except Exception:
                pass
            await fhem.readingsEndUpdate(self.hash, 1)
        else:
            if (
                reply is not None
                and isinstance(reply, str)
                and reply.lower() != "['ok']"
            ):
                await fhem.readingsSingleUpdateIfChanged(
                    self.hash, fct.__name__, reply, 1
                )
        if fct_name != "status":
            # wait before status request as it takes some time for the miio device
            # to change the state
            await asyncio.sleep(2)
            await self.send_command("status", None)
