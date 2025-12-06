# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service, get_ned_id

import re

# ------------------------
# SERVICE CALLBACK EXAMPLE
# ------------------------
class DeployCustomers(Service):
    
    def init(self, type):
        self.type = type
        self.log.info('Service on deploy : ', type)

    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')
        template = ncs.template.Template(service)
        vars = ncs.template.Variables()

        # initialisation variables Yang <--> template XML
        pe_attr = service.pe_attributes
        pe_id = pe_attr.id
        
        # variables issues du modèle YANG communes à tous les types de services
        vars.add("SERVICE_NAME", self.type)
        vars.add("CUSTOMER_NAME", service.customer_name)
        vars.add("PE_ID", pe_id)
        vars.add("PE_PORT_ID", pe_attr.port_id)
        vars.add("PE_PORT_CONNECTOR", str(pe_attr.port_id).rsplit('/', 1)[0])  # extraction de la partie avant le dernier '/'
        vars.add("PE_INTF_IPV4_ADDR", pe_attr.ipv4_addr)
        vars.add("PE_INTF_IPV4_MASK", pe_attr.cidr_mask)
        
        if self.type == "TSP":           
            # récupération de l'autonomous-system du PE en lisant la configuration courante du routeur
            autonomous_system = root.devices.device[pe_id].config.configure.router['Base'].autonomous_system
            pe_loopback_system = root.devices.device[pe_id].config.configure.router['Base'].interface['system'].ipv4.primary.address

            vars.add("PE_AS", autonomous_system)
            vars.add("PE_LOOPBACK_SYSTEM", pe_loopback_system)

            template.apply(f"nokia_sros_netconf_TSP", vars)

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):

        self.log.info('Main RUNNING')
        self.register_service('deploy-customers-TSP-servicepoint', DeployCustomers, 'TSP')
    

    def teardown(self):

        self.log.info('Main FINISHED')
