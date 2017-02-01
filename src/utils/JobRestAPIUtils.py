import json
import os
import time
import argparse
import uuid
import subprocess
import sys
from jobs_tensorboard import GenTensorboardMeta

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"../storage"))
from gen_pv_pvc import GenStorageClaims, GetStoragePath

import yaml
from jinja2 import Environment, FileSystemLoader, Template
from config import config
from DataHandler import DataHandler
import base64


def LoadJobParams(jobParamsJsonStr):
    return json.loads(jobParamsJsonStr)


def SubmitJob(jobParamsJsonStr):
    ret = {}

    jobParams = LoadJobParams(jobParamsJsonStr)
    print jobParamsJsonStr

    dataHandler = DataHandler()

    if "jobId" not in jobParams or jobParams["jobId"] == "":
        #jobParams["jobId"] = jobParams["jobName"] + "-" + str(uuid.uuid4()) 
        #jobParams["jobId"] = jobParams["jobName"] + "-" + str(time.time())
        jobParams["jobId"] = str(uuid.uuid4()) 
    #jobParams["jobId"] = jobParams["jobId"].replace("_","-").replace(".","-")


    if "cmd" not in jobParams:
        jobParams["cmd"] = ""

    if "jobPath" in jobParams and len(jobParams["jobPath"].strip()) > 0: 
        jobPath = jobParams["jobPath"]
    else:
        jobPath = time.strftime("%y%m%d")+"/"+jobParams["jobId"]
        jobParams["jobPath"] = jobPath

    if "workPath" not in jobParams or len(jobParams["workPath"].strip()) == 0: 
       ret["error"] = "ERROR: work-path cannot be empty"

    if "dataPath" not in jobParams or len(jobParams["dataPath"].strip()) == 0: 
        ret["error"] = "ERROR: data-path cannot be empty"


    if "logDir" in jobParams and len(jobParams["logDir"].strip()) > 0:
        tensorboardParams = jobParams.copy()

        tensorboardParams["jobId"] = str(uuid.uuid4()) 
        tensorboardParams["jobName"] = "tensorboard-"+jobParams["jobName"]
        tensorboardParams["jobPath"] = jobPath
        tensorboardParams["jobType"] = "visualization"
        tensorboardParams["cmd"] = "tensorboard --logdir " + jobParams["logDir"] + " --host 0.0.0.0"
        tensorboardParams["image"] = "tensorflow/tensorflow:latest"
        tensorboardParams["resourcegpu"] = "0"


        tensorboardParams["serviceId"] = "tensorboard-"+tensorboardParams["jobId"]
        tensorboardParams["port"] = "6006"
        tensorboardParams["port-name"] = "tensorboard"
        tensorboardParams["port-type"] = "TCP"       

        if "error" not in ret:
            if not dataHandler.AddJob(tensorboardParams):
                ret["error"] = "Cannot schedule tensorboard job."


    if "error" not in ret:
        if dataHandler.AddJob(jobParams):
            ret["jobId"] = jobParams["jobId"]
        else:
            ret["error"] = "Cannot schedule job. Cannot add job into database."




    return ret



def GetJobList(userName):
    dataHandler = DataHandler()
    jobs =  dataHandler.GetJobList(userName)
    for job in jobs:
        job.pop('jobMeta', None)
    return jobs



def KillJob(jobId):
    dataHandler = DataHandler()
    jobs =  dataHandler.GetJob(jobId)
    if len(jobs) == 1:
        return dataHandler.KillJob(jobId)
    return False


def GetJobDetail(jobId):
    job = None
    dataHandler = DataHandler()
    jobs =  dataHandler.GetJob(jobId)
    if len(jobs) == 1:
        job = jobs[0]
        job["log"] = ""
        #jobParams = json.loads(base64.b64decode(job["jobMeta"]))
        #jobPath,workPath,dataPath = GetStoragePath(jobParams["jobPath"],jobParams["workPath"],jobParams["dataPath"])
        #localJobPath = os.path.join(config["storage-mount-path"],jobPath)
        #logPath = os.path.join(localJobPath,"joblog.txt")
        #print logPath
        #if os.path.isfile(logPath):
        #    with open(logPath, 'r') as f:
        #        log = f.read()
        #        job["log"] = log
        #    f.close()
        if "jobDescription" in job:
            job.pop("jobDescription",None)
        log = dataHandler.GetJobTextField(jobId,"jobLog")
        if log is not None:
            job["log"] = log
    return job


##############################################################################################################################

def SubmitDistJob(jobParamsJsonStr,tensorboard=False):
    

    jobTempDir = os.path.join(config["root-path"],"Jobs_Templete")
    workerJobTemp= os.path.join(jobTempDir, "DistTensorFlow_worker.yaml.template")
    psJobTemp= os.path.join(jobTempDir, "DistTensorFlow_ps.yaml.template")

    jobParams = LoadJobParams(jobParamsJsonStr)
    if "jobId" not in jobParams or jobParams["jobId"] == "":
        #jobParams["jobId"] = jobParams["jobName"] + "-" + str(uuid.uuid4()) 
        jobParams["jobId"] = jobParams["jobName"] + "-" + str(time.time())
    jobParams["jobId"] = jobParams["jobId"].replace("_","-").replace(".","-")

    if "cmd" not in jobParams:
        jobParams["cmd"] = ""


    if "jobPath" in jobParams and len(jobParams["jobParams"].strip()) > 0: 
        jobPath = jobParams["jobPath"]
    else:
        jobPath = time.strftime("%y%m%d")+"/"+jobParams["jobId"]

    if "workPath" not in jobParams or len(jobParams["workPath"].strip()) == 0: 
        raise Exception("ERROR: work-path cannot be empty")

    if "dataPath" not in jobParams or len(jobParams["dataPath"].strip()) == 0: 
        raise Exception("ERROR: data-path cannot be empty")


    if "worker-num" not in jobParams:
        raise Exception("ERROR: unknown number of workers")
    if "ps-num" not in jobParams:
        raise Exception("ERROR: unknown number of parameter servers")

    numWorker = int(jobParams["worker-num"])
    numPs = int(jobParams["ps-num"])

    jobPath,workPath,dataPath = GetStoragePath(jobPath,jobParams["workPath"],jobParams["dataPath"])

    localJobPath = os.path.join(config["storage-mount-path"],jobPath)

    if not os.path.exists(localJobPath):
        os.makedirs(localJobPath)

    jobDir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "jobfiles")
    if not os.path.exists(jobDir):
        os.mkdir(jobDir)

    jobDir = os.path.join(jobDir,time.strftime("%y%m%d"))
    if not os.path.exists(jobDir):
        os.mkdir(jobDir)

    jobDir = os.path.join(jobDir,jobParams["jobId"])
    if not os.path.exists(jobDir):
        os.mkdir(jobDir)

    jobFilePath = os.path.join(jobDir, jobParams["jobId"]+".yaml")    

    ENV = Environment(loader=FileSystemLoader("/"))


    jobTempList= []
    workerHostList = []
    psHostList = []
    for i in range(numWorker):
        workerHostList.append(jobParams["jobId"]+"-worker"+str(i)+":2222")


    for i in range(numPs):
        psHostList.append(jobParams["jobId"]+"-ps"+str(i)+":2222")


    workerHostStr = ",".join(workerHostList)
    psHostStr = ",".join(psHostList)

    cmdStr = jobParams["cmd"]


    jobParams["pvc_job"] = "jobs-"+jobParams["jobId"]
    jobParams["pvc_work"] = "work-"+jobParams["jobId"]
    jobParams["pvc_data"] = "storage-"+jobParams["jobId"]


    pv_meta_j,pvc_meta_j = GenStorageClaims(jobParams["pvc_job"],jobPath)
    pv_meta_u,pvc_meta_u = GenStorageClaims(jobParams["pvc_work"],workPath)
    pv_meta_d,pvc_meta_d = GenStorageClaims(jobParams["pvc_data"],dataPath)

    jobTempList.append(pv_meta_j)
    jobTempList.append(pvc_meta_j)
    jobTempList.append(pv_meta_u)
    jobTempList.append(pvc_meta_u)
    jobTempList.append(pv_meta_d)
    jobTempList.append(pvc_meta_d)

    for i in range(numWorker):
        jobParams["worker-id"]=str(i)

        cmdList = cmdStr.split(" ")
        cmdList.append("--worker_hosts="+workerHostStr)
        cmdList.append("--ps_hosts="+psHostStr)
        cmdList.append("--job_name=worker")
        cmdList.append("--task_index="+str(i))

        jobParams["cmd"] = "[ " + ",".join(["\""+s+"\"" for s in cmdList if len(s.strip())>0])+ " ]"

        template = ENV.get_template(os.path.abspath(workerJobTemp))
        jobTempList.append(template.render(job=jobParams))


    for i in range(numPs):
        jobParams["ps-id"]=str(i)

        cmdList = cmdStr.split(" ")
        cmdList.append("--worker_hosts="+workerHostStr)
        cmdList.append("--ps_hosts="+psHostStr)
        cmdList.append("--job_name=ps")
        cmdList.append("--task_index="+str(i))

        jobParams["cmd"] = "[ " + ",".join(["\""+s+"\"" for s in cmdList if len(s.strip())>0])+ " ]"


        template = ENV.get_template(os.path.abspath(psJobTemp))
        jobTempList.append(template.render(job=jobParams))



    jobMeta = "\n---\n".join(jobTempList)


    if "logdir" in jobParams and len(jobParams["logdir"].strip()) > 0:
        jobParams["svc-name"] = "tensorboard-"+jobParams["jobId"]
        jobParams["app-name"] = "tensorboard-"+jobParams["jobId"]
        jobParams["port"] = "6006"
        jobParams["port-name"] = "tensorboard"
        jobParams["port-type"] = "TCP"        
        jobParams["tensorboard-id"] = "tensorboard-"+jobParams["jobId"]

        tensorboardMeta = GenTensorboardMeta(jobParams, os.path.join(jobTempDir,"KubeSvc.yaml.template"), os.path.join(jobTempDir,"TensorboardApp.yaml.template"))

        tensorboardMetaFilePath = os.path.join(jobDir, "tensorboard-"+jobParams["jobId"]+".yaml")

        with open(tensorboardMetaFilePath, 'w') as f:
            f.write(tensorboardMeta)

        output = kubectl_create(tensorboardMetaFilePath)

    with open(jobFilePath, 'w') as f:
        f.write(jobMeta)

    output = kubectl_create(jobFilePath)    

    ret={}
    ret["output"] = output
    ret["jobId"] = jobParams["jobId"]


    jobParams["jobDescriptionPath"] = jobFilePath
    jobParams["jobDescription"] = base64.b64encode(jobMeta)
    if "userName" not in jobParams:
        jobParams["userName"] = ""
    dataHandler = DataHandler()
    dataHandler.AddJob(jobParams)

    return ret





def GetJob(jobId):
    dataHandler = DataHandler()
    job =  dataHandler.GetJob(jobId)
    return job

def DeleteJob(jobId):
    dataHandler = DataHandler()
    jobs =  dataHandler.GetJob(jobId)
    if len(jobs) == 1:
        kubectl_exec(" delete -f "+jobs[0]["job_meta_path"])
        dataHandler.DelJob(jobId)
    return


def Split(text,spliter):
    return [x for x in text.split(spliter) if len(x.strip())>0]

def GetServiceAddress(jobId):
    ret = []

    output = kubectl_exec(" describe svc -l run="+jobId)
    svcs = output.split("\n\n\n")
    
    for svc in svcs:
        lines = [Split(x,"\t") for x in Split(svc,"\n")]
        port = None
        nodeport = None
        selector = None
        hostIP = None

        for line in lines:
            if len(line) > 1:
                if line[0] == "Port:":
                    port = line[-1]
                    if "/" in port:
                        port = port.split("/")[0]
                if line[0] == "NodePort:":
                    nodeport = line[-1]
                    if "/" in nodeport:
                        nodeport = nodeport.split("/")[0]

                if line[0] == "Selector:" and line[1] != "<none>":
                    selector = line[-1]

        if selector is not None:
            podInfo = GetPod(selector)
            if podInfo is not None and "items" in podInfo:
                for item in podInfo["items"]:
                    if "status" in item and "hostIP" in item["status"]:
                        hostIP = item["status"]["hostIP"]
        if port is not None and hostIP is not None and nodeport is not None:
            ret.append( (port,hostIP,nodeport))
    return ret


def GetTensorboard(jobId):
    output = kubectl_exec(" describe svc tensorboard-"+jobId)
    lines = [Split(x,"\t") for x in Split(output,"\n")]
    port = None
    nodeport = None
    selector = None
    hostIP = None

    for line in lines:
        if len(line) > 1:
            if line[0] == "Port:":
                port = line[-1]
                if "/" in port:
                    port = port.split("/")[0]
            if line[0] == "NodePort:":
                nodeport = line[-1]
                if "/" in nodeport:
                    nodeport = nodeport.split("/")[0]

            if line[0] == "Selector:" and line[1] != "<none>":
                selector = line[-1]

    if selector is not None:
        output = kubectl_exec(" get pod -o yaml -l "+selector)
        podInfo = yaml.load(output)

        
        for item in podInfo["items"]:
            if "status" in item and "hostIP" in item["status"]:
                hostIP = item["status"]["hostIP"]

    return (port,hostIP,nodeport)

def GetPod(selector):
    try:
        output = kubectl_exec(" get pod -o yaml --show-all -l "+selector)
        podInfo = yaml.load(output)
    except Exception as e:
        print e
        podInfo = None
    return podInfo



def GetJobStatus(jobId):
    pods = GetPod("run="+jobId)["items"]
    output = "unknown"
    detail = "Unknown Status"
    if len(pods) > 0:
        lastpod = pods[-1]
        if "status" in lastpod and "phase" in lastpod["status"]:
            output = lastpod["status"]["phase"]
            detail = yaml.dump(lastpod["status"], default_flow_style=False)
    return output, detail


if __name__ == '__main__':
    TEST_SUB_REG_JOB = False
    TEST_JOB_STATUS = True
    TEST_DEL_JOB = False
    TEST_GET_TB = False
    TEST_GET_SVC = False
    TEST_GET_LOG = False

    if TEST_SUB_REG_JOB:
        parser = argparse.ArgumentParser(description='Launch a kubernetes job')
        parser.add_argument('-f', '--param-file', required=True, type=str,
                            help = 'Path of the Parameter File')
        parser.add_argument('-t', '--template-file', required=True, type=str,
                            help = 'Path of the Job Template File')
        args, unknown = parser.parse_known_args()
        with open(args.param_file,"r") as f:
            jobParamsJsonStr = f.read()
        f.close()

        SubmitRegularJob(jobParamsJsonStr,args.template_file)

    if TEST_JOB_STATUS:
        print GetJobStatus(sys.argv[1])

    if TEST_DEL_JOB:
        print DeleteJob("tf-dist-1483504085-13")

    if TEST_GET_TB:
        print GetTensorboard("tf-resnet18-1483509537-31")

    if TEST_GET_SVC:
        print GetServiceAddress("tf-i-1483566214-12")

    if TEST_GET_LOG:
        print GetLog("tf-i-1483566214-12")