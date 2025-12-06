# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service


# ------------------------
# SERVICE CALLBACK EXAMPLE
# ------------------------
class TrafficEngineering(Service):
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')

        template = ncs.template.Template(service)
        vars = ncs.template.Variables()

        # récupération des variables issues du modèle YANG
        vars.add("SOURCE_DEVICE", service.source)
        vars.add("DESTINATION_DEVICE", service.destination)
        vars.add("COLOR", service.color)
        vars.add("SERVICE_TYPE", service.service_type.string)
        vars.add("SERVICE_NAME", service.service_name)

        destination_ip = root.devices.device[service.destination].config.configure.router['Base'].interface['system'].ipv4.primary.address
        self.log.info(f'Destination IP for device {service.destination}: {destination_ip}')
        vars.add("DESTINATION_IP", destination_ip)
        
        # Application du template pour la configuration du routeur source
        label_path = service.label_path.as_list()
        for index, label in enumerate(label_path, start=1):
            vars.add("INDEX_PATH", index)
            vars.add("LABEL_PATH", label)
            self.log.info(f'Configuring label {label} with index {index} for source device {service.source} to destination device {service.destination}')
            template.apply("traffic-engineering-source-template", vars)

        # Application du template pour la configuration du routeur de destination
        export_policies = root.devices.device[service.destination].config.configure.service.vprn[service.service_name].bgp_ipvpn.mpls.vrf_export.policy
        for export_policy in export_policies:
            self.log.info(f'Getting Export policy {export_policy} on destination device {service.destination} in service {service.service_name}')
            vars.add("EXPORT_POLICY_NAME", export_policy)
            entries = root.devices.device[service.destination].config.configure.policy_options.policy_statement[export_policy].entry
            for entry in entries:
                self.log.info(f'configuring entry {entry.entry_id} in export policy {export_policy}')
                vars.add("ENTRY", entry.entry_id)
                template.apply("traffic-engineering-destination-template", vars)




        

# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        self.log.info('Main RUNNING')
        self.register_service('traffic-engineering-servicepoint', TrafficEngineering)

    def teardown(self):
        self.log.info('Main FINISHED')
