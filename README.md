# Operations-LLM-Agent  
A lightweight LLM agent for service operations  

目標 (Goal):  
打造一個供專案經理 (PM)、業務和工程師使用的維運 Agent，能夠以自然語言執行任務。  
目前處於開發階段，假設使用氣象局空開 API 作為後端服務的範例。  

To create a maintenance agent that can be used by project managers (PMs), sales and engineers, enabling them to execute tasks using natural language.
Currently in the development phase, with a hypothetical backend service based on the Meteorological Bureau's Open API as an example.


---

## Features (已完成功能)  

1. **Retrieve real-time data for a target site.**  
   即時獲取目標場域的即時資料。  
2. **Establish a scheduled observation service.**  
   建立排程服務，定期觀察目標場域資料。  

---

## Prerequisites (系統需求)  

- 運行 *service-operation-agent* 的環境需已 Docker 化。  
- 啟動服務前，請確認以下工具已安裝：  
  - [Docker CE](https://docs.docker.com/install/)  
  - [Docker Compose](https://docs.docker.com/compose/install/)  
- 獲取可用的 LLM 資訊，並更新至 `./docker/linux/agent.env` 文件中。  

The service-operation-agent must run in a Dockerized environment.
Before starting the service, ensure the following tools are installed:
Docker CE
Docker Compose
Obtain valid LLM credentials and update them in the ./docker/linux/agent.env file.
---

## Build the Service (建置服務)  
運行以下指令以建置 Docker 映像檔：  
```bash
./docker/linux/run_build_image.sh
```  

---

## Start the Service (啟動服務)  
運行以下指令以啟動服務：  
```bash
./docker/linux/run_service.sh
```  
服務啟動後，可透過瀏覽器開啟以下 URL 查看服務資訊：  
`http://{your-host-ip}:{service-port}/docs`  
例如：`http://127.0.0.1:8001/docs`  

---

## Remove the Service (移除服務)  
運行以下指令以停止並完全移除已部署的 Docker 容器：  
```bash
./docker/linux/remove_service.sh
```  

---

> This project is a work in progress and welcomes contributions or feedback.  
> 本專案正在開發中，歡迎提供建議或貢獻！  
