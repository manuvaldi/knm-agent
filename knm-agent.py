#!/usr/bin/python

import urllib2
import sys
import getopt
import json
import subprocess
import xmltodict
import re
from netaddr import IPNetwork

main_interface = 'eth0'
url = 'http://127.0.0.1:5000/network.json'
servername = ''

def main(argv):
   global main_interface, servername
   try:
      opts, args = getopt.getopt(argv,"hu:s:m:",["url=","servername=","maininterface="])
   except getopt.GetoptError:
      print 'test.py -u <server url> -s <server name>'
      sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
         print 'test.py -u <server url> -s <server name>'
         sys.exit()
      elif opt in ("-u", "--url"):
         url = arg
      elif opt in ("-m", "--maininterface"):
         main_interface = arg
      elif opt in ("-s", "--servername"):
         servername = arg
   print 'URL is ', url
   print 'Server name is ', servername

   contents = urllib2.urlopen(url+'/'+servername).read()
   networks = json.loads(contents)
   current_networks = libvirt_current_networks()

   config_networks=[]
   for net in networks:
       if (servername in net['servers'].split(',')):
           config_networks.append(net['name'])
           print("\nChecking network '"+net['name']+"'")
           if net['name'] in current_networks:
               if networks_equal(net):
                  print "Nothing to do with "+net['name']
               else:
                  print("Change network")
                  change_network(net)
                #   change_network(net)
           else:
               print("Create network")
               create_network(net)

   for net in current_networks:
        if not net in config_networks:
            print("Deleting "+net)
            delete_network(net)


def run_cmd(cmd, verbose = False):
    if (verbose == True): print("\nRunning: "+cmd)
    process = subprocess.Popen(' stdbuf -o0 ' + cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, shell=True )
    out = a = ""
    while True:
        # sys.stdout.flush()
        out = process.stdout.read(1)
        if out == '' and process.poll() != None:
            break
        if out != '':
            a += out
            if (verbose == True): print(out)
    returnCode = process.poll()
    if (returnCode != 0):
        print(a)
    return a


def create_and_assigne_vlan(net):
    xml = run_cmd('virsh -c qemu:///system net-dumpxml '+net['name'])

    # Only bridge vlan assigment
    bridge_name = re.search('virbr\d+', xml).group()
    vlan_interface = main_interface+'.'+net['vlanid']
    run_cmd('ip link add link '+main_interface+' name '+vlan_interface+' type vlan id '+net['vlanid'])
    run_cmd('ip link set '+vlan_interface+' up')
    run_cmd('brctl addif '+bridge_name+' '+vlan_interface)

def change_network(net):

    create_and_assigne_vlan(net)


def create_network(net):
    global servername

    try:
        server_index = net['servers'].split(',').index(servername)
    except:
        print("Network do not apply to this host")
        return

    cmd = 'kcli network -c '+net['cidr']+' '

    # It's not the first server
    if server_index != 0 or not ("D" in list(net['options'])): cmd += ' --nodhcp --isolated '

    if ("I" in list(net['options'])): cmd += ' --isolated '

    cmd += net['name']

    print "Executing: "+cmd
    run_cmd(cmd)

    xml = run_cmd('virsh -c qemu:///system net-dumpxml '+net['name'])
    # o = xmltodict.parse(xml)

    last_octect=int(net['cidr'].split("/")[0].split(".")[3])+1+server_index
    xml_new = re.sub("ip address='(([0-9]{1,3}\.){2}[0-9]{1,3})\.([0-9]{1,3})'", r"ip address='\1.%s'" % last_octect, xml)

    #TODO remove dhcp section in server_index != 0
    #xml_new = re.sub("ip address='(([0-9]{1,3}\.){2}[0-9]{1,3})\.([0-9]{1,3})'", r"ip address='\1.%s'" % last_octect, xml)

    text_file = open('/tmp/'+net['name']+'.xml', "w")
    text_file.write(xml_new)
    text_file.close()

    run_cmd('virsh -c qemu:///system net-destroy '+net['name'])
    run_cmd('virsh -c qemu:///system net-undefine '+net['name'])
    run_cmd('virsh -c qemu:///system net-define /tmp/'+net['name']+'.xml ')
    run_cmd('virsh -c qemu:///system net-start '+net['name'])
    run_cmd('virsh -c qemu:///system net-autostart '+net['name'])

    # # bridge_name = re.sub(r".*<bridge name='(.*)?'", r"\2", xml.replace('\n',''))
    # bridge_name = re.search('virbr\d+', xml).group()
    # vlan_interface = main_interface+'.'+net['vlanid']
    # run_cmd('ip link add link '+main_interface+' name '+vlan_interface+' type vlan id '+net['vlanid'])
    # run_cmd('ip link set '+vlan_interface+' up')
    # run_cmd('brctl addif '+bridge_name+' '+vlan_interface)
    create_and_assigne_vlan(net)


def delete_network(net):

    xml = run_cmd('virsh -c qemu:///system net-dumpxml '+net)
    bridge_name = re.search('virbr\d+', xml).group()
    bridge_main_vlan_interfaces = run_cmd('brctl show '+bridge_name+' | tr "\t" "\n" | grep '+main_interface).strip()

    # print bridge_name
    # print bridge_main_vlan_interfaces

    if (bridge_main_vlan_interfaces != ""):
        run_cmd('brctl delif '+bridge_name+' '+bridge_main_vlan_interfaces)
        run_cmd('ip link set '+bridge_main_vlan_interfaces+' down')
        run_cmd('ip link delete '+bridge_main_vlan_interfaces)

    run_cmd('virsh -c qemu:///system net-destroy '+net)
    run_cmd('virsh -c qemu:///system net-undefine '+net)



def networks_equal(net):
    installed_network_xml = run_cmd('virsh -c qemu:///system net-dumpxml '+net['name'])
    o = xmltodict.parse(installed_network_xml)
    # print json.dumps(o, indent=4, sort_keys=True)
    bridge_name = re.search('virbr\d+', installed_network_xml).group()
    bridge_show = run_cmd('brctl show '+bridge_name)
    vlan_interface = main_interface+'.'+net['vlanid']


    # cidr
    cidr = str(IPNetwork(o['network']['ip']['@address']+'/'+o['network']['ip']['@netmask']).cidr)
    if ( cidr != net['cidr'] ):  return False
    # print("CIDR match")

    # isolated or nat
    try:
        nat = o['network']['forward']['@mode']
    except:
        nat = ""
    # print("nat---")
    # print(nat)
    # print(net['options'])
    if (nat == "nat" and ("I" in list(net['options']))):  return False
    if (nat == "" and not ("I" in list(net['options']))): return False
    # print("NAT match")

    # dhcp enable
    try:
        dhcp = o['network']['ip']['dhcp']
    except:
        dhcp = ""
    # print("---")
    # print(dhcp)
    # print(net['options'])
    if (dhcp != "" and not ("D" in list(net['options']))): return False
    if (dhcp == "" and ("D" in list(net['options']))): return False
    # print("DHCP match")
    # Bridge and VLAN interface

    # VLAN interface in bridge
    # print("vlan: "+vlan_interface)
    try:
        vlan_bridge_grep = re.search(vlan_interface, bridge_show).group()
    except:
        vlan_bridge_grep = "none-none"
    # print("grep: "+vlan_bridge_grep)
    if (vlan_bridge_grep != vlan_interface): return False


    return True


def libvirt_current_networks():
    networks = run_cmd('virsh -c qemu:///system net-list --name').split()
    return networks


def netmask_to_cidr(netmask):
    return str(sum([bin(int(x)).count('1') for x in netmask.split('.')]))



if __name__ == "__main__":
   main(sys.argv[1:])
