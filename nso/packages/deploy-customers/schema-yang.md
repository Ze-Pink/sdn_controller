# Schéma de Modélisation YANG - deploy-customers

## Structure Hiérarchique

```
deploy-customers (module)
│
└── deploy-customers (container)
    │
    └── service-TSP (list)
        │
        ├── customer-name (key, leaf) [string]
        │
        ├── service-data (uses ncs:service-data)
        │
        └── pe-attributes (container)
            │
            ├── id (leaf) [leafref → /ncs:devices/ncs:device/ncs:name]
            │
            ├── port-id (leaf) [string, mandatory]
            │
            ├── ipv4-addr (leaf) [inet:ipv4-address, mandatory]
            │
            └── cidr-mask (leaf) [int8]
```

## Diagramme Détaillé

```
┌─────────────────────────────────────────────────────────────────┐
│ Module: deploy-customers                                        │
│ Namespace: http://example.com/deploy-customers                  │
│ Prefix: deploy-customers                                        │
├─────────────────────────────────────────────────────────────────┤
│ Imports:                                                        │
│  • ietf-inet-types (prefix: inet)                              │
│  • tailf-common (prefix: tailf)                                │
│  • tailf-ncs (prefix: ncs)                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Container: deploy-customers                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ List: service-TSP                                               │
│ Key: customer-name                                              │
│ Servicepoint: deploy-customers-TSP-servicepoint                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Leaf: customer-name                                      │  │
│  │ Type: string                                             │  │
│  │ Role: Clé de la liste                                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Uses: ncs:service-data                                   │  │
│  │ (Données de service NSO standard)                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Container: pe-attributes                                 │  │
│  │ (Attributs du Provider Edge Router)                      │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐ │  │
│  │  │ Leaf: id                                           │ │  │
│  │  │ Type: leafref                                      │ │  │
│  │  │ Path: /ncs:devices/ncs:device/ncs:name            │ │  │
│  │  │ Description: Référence au device NSO              │ │  │
│  │  └────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐ │  │
│  │  │ Leaf: port-id                                      │ │  │
│  │  │ Type: string                                       │ │  │
│  │  │ Mandatory: true                                    │ │  │
│  │  │ Description: Identifiant du port                  │ │  │
│  │  └────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐ │  │
│  │  │ Leaf: ipv4-addr                                    │ │  │
│  │  │ Type: inet:ipv4-address                            │ │  │
│  │  │ Mandatory: true                                    │ │  │
│  │  │ Description: Adresse IPv4                          │ │  │
│  │  └────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐ │  │
│  │  │ Leaf: cidr-mask                                    │ │  │
│  │  │ Type: int8                                         │ │  │
│  │  │ Description: Masque CIDR (ex: 24 pour /24)        │ │  │
│  │  └────────────────────────────────────────────────────┘ │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Exemple d'Instance de Données

```xml
<deploy-customers xmlns="http://example.com/deploy-customers">
  <service-TSP>
    <customer-name>client-example</customer-name>
    <pe-attributes>
      <id>PE-Router-1</id>
      <port-id>GigabitEthernet0/0/1</port-id>
      <ipv4-addr>192.168.100.1</ipv4-addr>
      <cidr-mask>24</cidr-mask>
    </pe-attributes>
  </service-TSP>
</deploy-customers>
```

## Description du Service

**Objectif**: Ce service configure VRF et interfaces sur les routeurs pour connecter des clients

**Points Clés**:
- Liste de services par client (identifié par `customer-name`)
- Configuration des attributs du routeur PE (Provider Edge)
- Référence aux devices NSO via leafref
- Configuration d'interface avec adressage IPv4
- Intégration avec le servicepoint NSO pour l'automatisation

**Champs Obligatoires**:
- `customer-name`: Nom du client
- `port-id`: Identifiant du port
- `ipv4-addr`: Adresse IPv4

**Champs Optionnels**:
- `id`: Device NSO (recommandé)
- `cidr-mask`: Masque réseau
