# Copyright 2014 Plexxi, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Main entrypoint for the DSE
#
# Configuration in d6cage.ini
#
# Prerequisites:
# - Plexxi API libraries (there is an RPM)
# - Python dependencies (see readme elsewhere, or capture RPM)

import imp
import sys
import traceback

import amqprouter
import eventlet
eventlet.monkey_patch()

from congress.dse import d6message
from congress.dse import deepsix
from congress.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class DataServiceError (Exception):
    pass


class d6Cage(deepsix.deepSix):
    def __init__(self):
        self.config = {}
        self.config['modules'] = {}
        self.config['services'] = {}

        # Dictionary mapping service name to a dict of arguments.
        # Those arguments are only passed to d6service by createservice if they
        #   are not alreay present in the ARGS argument given to createservice.
        self.default_service_args = {}

        cageKeys = ['python.d6cage']
        cageDesc = 'deepsix python cage'
        name = "d6cage"

        deepsix.deepSix.__init__(self, name, cageKeys)

        self.inbox = eventlet.Queue()
        self.dataPath = eventlet.Queue()

        self.table = amqprouter.routeTable()
        self.table.add("local.router", self.inbox)
        self.table.add(self.name, self.inbox)
        self.table.add("router", self.inbox)

        localname = "local." + self.name
        self.table.add(localname, self.inbox)

        self.modules = {}
        self.services = {}

        self.greenThreadPool = eventlet.GreenPool()
        self.greenThreads = []

        self.unloadingServices = {}
        self.reloadingServices = set()

        self.services[self.name] = {}
        self.services[self.name]['service'] = self
        self.services[self.name]['name'] = self.name
        self.services[self.name]['description'] = cageDesc
        self.services[self.name]['inbox'] = self.inbox
        self.services[self.name]['keys'] = self.keys

        self.subscribe(
            "local.d6cage",
            "routeKeys",
            callback=self.updateRoutes,
            interval=5)

        # Set of service names that we deem special
        self.system_service_names = set([self.name])

    def __del__(self):
        # This function gets called when the interpreter deletes the object
        # by the automatic garbage cleanup
        for gt in self.greenThreads:
            eventlet.kill(gt)

        eventlet.kill(self)

    def newConfig(self, msg):
        newConfig = msg.body.data
        if type(newConfig) == dict and newConfig:
            if "modules" in newConfig:
                for module in newConfig["modules"]:
                    if module not in sys.modules:
                        self.loadModule(
                            module,
                            newConfig['modules'][module]['filename'])

            if "services" in newConfig:
                for service in newConfig['services']:
                    if service not in self.services:
                        self.createservice(
                            service,
                            **newConfig['services'][service])

            self.config = newConfig

    def reloadStoppedService(self, service):
        moduleName = self.config['services'][service]['moduleName']

        try:
            reload(sys.modules[moduleName])
        except Exception as errmsg:
            self.log_error(
                "Unable to reload module '%s': %s", moduleName, errmsg)
            return

        self.createservice(service, **self.config['services'][service])

    def waitForServiceToStop(
            self,
            service,
            attemptsLeft=20,
            callback=None,
            cbkwargs={}):

        if attemptsLeft > 0:

            if self.services[service]['object'].isActive():

                self.timerThreads.append(
                    eventlet.spawn_after(10,
                                         self.waitForServiceToStop,
                                         service,
                                         attemptsLeft - 1))

            else:

                del self.services[service]

                if callback:
                    callback(**cbkwargs)

        else:
            self.log_error("Unable to stop service %s", service)

    def loadModule(self, name, filename):
        if name in sys.modules:
            # self.log_error(
            #     "error loading module '%s': module already exists", name)
            return
        try:
            self.log_info("loading module: %s", name)
            imp.load_source(name, filename)
        except Exception:
            raise DataServiceError(
                "error loading module '%s' from '%s': %s" %
                (name, filename, traceback.format_exc()))

    def load_modules_from_config(self):
        for section in self.config['modules'].keys():
            filename = self.config['modules'][section]["filename"]

            self.loadModule(section, filename)

    def createservice(
            self,
            name="",
            keys="",
            description="",
            moduleName="",
            args={}):

        self.log_info("creating service %s with module %s and args %s",
                      name, moduleName, args)

        if moduleName not in sys.modules:
            raise DataServiceError(
                "error loading service" + name +
                ": module " + moduleName + " does not exist")

        if name in self.services:
            raise DataServiceError(
                "error loading service '%s': name already in use"
                % name)

        inbox = eventlet.Queue()
        module = sys.modules[moduleName]

        # set args to default values, as necessary
        if name in self.default_service_args:
            global_args = self.default_service_args[name]
            for key, value in global_args.items():
                if key not in args:
                    args[key] = value

        try:
            svcObject = module.d6service(name, keys, inbox, self.dataPath,
                                         args)

            self.greenThreadPool.spawn(svcObject.switch)
            self.greenThreads.append(svcObject)
        except Exception:
            raise DataServiceError(
                "Error loading service '%s' of module '%s':: \n%s"
                % (name, module, traceback.format_exc()))

        self.log_info("created service: %s", name)
        self.services[name] = {}
        self.services[name]['name'] = name
        self.services[name]['description'] = description
        self.services[name]['moduleName'] = moduleName
        self.services[name]['keys'] = keys
        self.services[name]['args'] = args
        self.services[name]['object'] = svcObject
        self.services[name]['inbox'] = inbox

        try:
            self.table.add(name, inbox)
            localname = "local." + name
            self.table.add(localname, inbox)

            self.subscribe(
                name,
                'routeKeys',
                callback=self.updateRoutes,
                interval=5)

            self.publish('services', self.services)
        except Exception as errmsg:
            del self.services[name]
            raise DataServiceError(
                "error starting service '%s': %s" % (name, errmsg))

    def updateRoutes(self, msg):
        keyData = self.getSubData(msg.correlationId, sender=msg.replyTo)
        currentKeys = set(keyData.data)
        self.log_debug("updateRoutes msgbody: %s", msg.body.data)
        pubKeys = set(msg.body.data['keys'])

        if currentKeys != pubKeys:

            newKeys = pubKeys - currentKeys

            if newKeys:
                self.table.add(
                    list(newKeys), self.services[msg.replyTo]['inbox'])

            oldKeys = currentKeys - pubKeys

            if oldKeys:
                self.table.remove(
                    list(oldKeys), self.services[msg.replyTo]['inbox'])

            return msg.body

    def load_services_from_config(self):

        for section in self.config['services'].keys():

            self.createservice(section, **self.config['services'][section])

    def routemsg(self, msg):
        # LOG.debug(
        #     "Message lookup %s from %s", msg.key, msg.replyTo)

        destinations = self.table.lookup(msg.key)
        # self.log_debug("Destinations %s for key %s for msg %s",
        #     destinations, msg.key, msg)

        if destinations:
            for destination in destinations:
                destination.put_nowait(msg)
                # self.log_debug("Message sent to %s from %s: %s",
                #                 msg.key, msg.replyTo, msg)

    def d6reload(self, msg):

        inargs = msg.body.data

        service = inargs['service']

        newmsg = d6message.d6msg(key=service, replyTo=self.name, type="shut")

        self.send(newmsg)
        cbkwargs = {}

        cbkwargs['service'] = service

        self.waitForServiceToStop(
            service,
            callback=self.reloadStoppedService,
            cbkwargs=cbkwargs)

    def cmdhandler(self, msg):

        command = msg.header['dataindex']

        if command == "reload":
            self.d6reload(msg)

    def d6run(self):
        # LOG.debug("d6cage running d6run()")
        if not self.dataPath.empty():
            # LOG.debug("%s has non-empty dataPath: %s",
            #     self.name, self.dataPath)
            msg = self.dataPath.get()
            # self.log_debug("found msg to deliver: %s", msg)
            self.routemsg(msg)
            self.dataPath.task_done()


if __name__ == '__main__':
    main = d6Cage

    try:
        main.wait()
        main.d6stop()
    except KeyboardInterrupt:
        main.d6stop()
        sys.exit(0)
