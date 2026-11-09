-- sql/schema.sql — banco vigia_de_rede (Fase 4)
-- Idempotente: IF NOT EXISTS em tudo. Rodar de novo só cria o que falta.
-- Alterações posteriores de schema vão por ALTER TABLE, não por recriar.

CREATE DATABASE IF NOT EXISTS vigia_de_rede CHARACTER SET utf8mb4;
USE vigia_de_rede;

-- Catálogo de dispositivos: identidade = MAC. É aqui que mora a whitelist.
CREATE TABLE IF NOT EXISTS TB_DISPOSITIVOS (
    id_dispositivo   INT AUTO_INCREMENT PRIMARY KEY,
    endereco_mac     VARCHAR(17) NOT NULL UNIQUE,
    nome_dispositivo VARCHAR(100),
    tipo_dispositivo VARCHAR(50),
    autorizado       BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE = na whitelist
    primeiro_visto   DATETIME,
    ultimo_visto     DATETIME,
    status           ENUM('ativo','inativo','desconhecido') DEFAULT 'desconhecido'
) ENGINE=InnoDB;

-- Cada ciclo de varredura
CREATE TABLE IF NOT EXISTS TB_VARREDURAS (
    id_varredura            INT AUTO_INCREMENT PRIMARY KEY,
    data_varredura          DATETIME NOT NULL,
    quantidade_dispositivos INT,
    total_portas            INT,
    total_alertas           INT,
    resultado_geral         VARCHAR(50),
    resumo                  TEXT
) ENGINE=InnoDB;

-- Quais dispositivos apareceram em cada varredura, e com qual IP na hora
CREATE TABLE IF NOT EXISTS TB_PRESENCAS (
    id_presenca    INT AUTO_INCREMENT PRIMARY KEY,
    id_varredura   INT NOT NULL,
    id_dispositivo INT NOT NULL,
    endereco_ip    VARCHAR(45),
    FOREIGN KEY (id_varredura)   REFERENCES TB_VARREDURAS(id_varredura),
    FOREIGN KEY (id_dispositivo) REFERENCES TB_DISPOSITIVOS(id_dispositivo)
) ENGINE=InnoDB;

-- Portas abertas num dispositivo específico, numa varredura específica
CREATE TABLE IF NOT EXISTS TB_PORTAS (
    id_porta      INT AUTO_INCREMENT PRIMARY KEY,
    id_presenca   INT NOT NULL,
    numero_porta  INT,
    protocolo     ENUM('tcp','udp'),
    servico       VARCHAR(100),
    status_porta  VARCHAR(20),
    FOREIGN KEY (id_presenca) REFERENCES TB_PRESENCAS(id_presenca)
) ENGINE=InnoDB;

-- Alertas gerados (ligados à varredura e, quando aplicável, ao dispositivo)
CREATE TABLE IF NOT EXISTS TB_ALERTAS (
    id_alerta      INT AUTO_INCREMENT PRIMARY KEY,
    id_varredura   INT NOT NULL,
    id_dispositivo INT,
    tipo_alerta    VARCHAR(50),
    descricao      TEXT,
    nivel_risco    ENUM('baixo','medio','alto','critico'),
    data_alerta    DATETIME,
    FOREIGN KEY (id_varredura)   REFERENCES TB_VARREDURAS(id_varredura),
    FOREIGN KEY (id_dispositivo) REFERENCES TB_DISPOSITIVOS(id_dispositivo)
) ENGINE=InnoDB;
