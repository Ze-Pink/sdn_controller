# Installation et pré-requis 

## Installation des packages sur la VM

### 1. Installer Docker et Docker Compose pour Ubuntu 24
```bash
# 1. Supprimer le dépôt Docker incorrect
sudo rm /etc/apt/sources.list.d/docker.list

# 2. Supprimer l'ancienne clé GPG
sudo rm /etc/apt/keyrings/docker.gpg

# 3. Télécharger la clé GPG pour Ubuntu
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 4. Ajouter le dépôt Docker pour Ubuntu
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. Mettre à jour et installer Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 6. Vérifier l'installation
sudo docker --version
sudo docker compose version

# 7. Ajouter votre utilisateur au groupe docker pour éviter sudo
sudo usermod -aG docker $USER
# Puis déconnectez-vous et reconnectez-vous
```

## 2. Images Docker nécessaires au projet
```
docker pull ghcr.io/ze-pink/neo4j:latest
docker pull ghcr.io/ze-pink/cisco-nso-prod:6.4.8
docker pull ghcr.io/ze-pink/vrnetlab/nokia_sros:24.10.r2
docker pull ghcr.io/ze-pink/alpine-minimal:latest
docker pull ghcr.io/ze-pink/gobgp_custom_3.37.0:3.37.0
```

## 3. Création d'un environnement python virtuel 
```bash
apt install python3.12-venv

python3 -m venv LAB_SDN_BYTEL

source LAB_SDN_BYTEL/bin/activate
```

### 4. Installer Python et pip
```bash
sudo apt install -y python3 python3-pip
pip3 --version
```


### 5. Installer les dépendances Python
```bash
pip install -r requirements.txt --break-system-packages
```


## 6. Installation de containerlab
```
echo "deb [trusted=yes] https://netdevops.fury.site/apt/ /" | \
sudo tee -a /etc/apt/sources.list.d/netdevops.list

sudo apt update && sudo apt install containerlab
```

## 7. Pré-requis au script Agent IA
S'assurer que les fichiers .env et .json soient bien présents dans le dossier scripts


## Déjà réalisé 
## Installation d'une image custom de GoBGP afin d'avoir un shell et de lancer des pings etc...
### Créer un fichier Dockerfile
```
FROM ghcr.io/ze-pink/alpine-minimal:latest

RUN apk add --no-cache curl tar && \
    curl -L https://github.com/osrg/gobgp/releases/download/v3.37.0/gobgp_3.37.0_linux_amd64.tar.gz \
      | tar -xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/gobgp /usr/local/bin/gobgpd

EXPOSE 50051

CMD ["/bin/sh"]
```

### Cloner le dossier GoBGP de la bonne version depuis GitHub : 
git clone https://github.com/osrg/gobgp.git

### Aller dans le dossier 'api' et executer la commande suivante afin de compiler les protobuf depuis le dossier api
```
python3 -m grpc_tools.protoc -I./ --python_out=. --grpc_python_out=. *.proto

Ceci va générer des fichiers pb2 : 
marco@ubuntu24:~/lab_tsp/containerlab/lab/tsp/gobgp/gobgp/proto/api$ ls | grep pb2
attribute_pb2.py
attribute_pb2_grpc.py
capability_pb2.py
capability_pb2_grpc.py
common_pb2.py
common_pb2_grpc.py
extcom_pb2.py
extcom_pb2_grpc.py
gobgp_pb2.py
gobgp_pb2_grpc.py
nlri_pb2.py
nlri_pb2_grpc.py
```
