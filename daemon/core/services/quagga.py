#
# CORE
# Copyright (c)2010-2012 the Boeing Company.
# See the LICENSE file included in this distribution.
#
# author: Jeff Ahrenholz <jeffrey.m.ahrenholz@boeing.com>
#
'''
quagga.py: defines routing services provided by Quagga. 
'''

import os

if os.uname()[0] == "Linux":
    from core.netns import nodes
elif os.uname()[0] == "FreeBSD":
    from core.bsd import nodes
from core.service import CoreService, addservice
from core.misc.ipaddr import IPv4Prefix, isIPv4Address, isIPv6Address
from core.api import coreapi
from core.constants import *

QUAGGA_USER="root"
QUAGGA_GROUP="root"
if os.uname()[0] == "FreeBSD":
    QUAGGA_GROUP="wheel"

class Zebra(CoreService):
    ''' 
    '''
    _name = "zebra"
    _group = "Quagga"
    _depends = ("vtysh", )
    _dirs = ("/usr/local/etc/quagga",  "/var/run/quagga")
    _configs = ("/usr/local/etc/quagga/Quagga.conf",
                "quaggaboot.sh","/usr/local/etc/quagga/vtysh.conf")
    _startindex = 35
    _startup = ("sh quaggaboot.sh zebra",)
    _shutdown = ("killall zebra", )
    _validate = ("pidof zebra", )

    @classmethod
    def generateconfig(cls, node, filename, services):
        ''' Return the Quagga.conf or quaggaboot.sh file contents.
        '''
        if filename == cls._configs[0]:
            return cls.generateQuaggaConf(node, services)
        elif filename == cls._configs[1]:
            return cls.generateQuaggaBoot(node, services)
        elif filename == cls._configs[2]:
            return cls.generateVtyshConf(node, services)
        else:
            raise ValueError
        
    @classmethod
    def generateVtyshConf(cls, node, services):
        ''' Returns configuration file text.
        '''
        return "service integrated-vtysh-config\n"

    @classmethod
    def generateQuaggaConf(cls, node, services):
        ''' Returns configuration file text. Other services that depend on zebra
           will have generatequaggaifcconfig() and generatequaggaconfig()
           hooks that are invoked here.
        '''
        # we could verify here that filename == Quagga.conf
        cfg = ""
        for ifc in node.netifs():
            cfg += "interface %s\n" % ifc.name
            # include control interfaces in addressing but not routing daemons
            if hasattr(ifc, 'control') and ifc.control == True:
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ifc.addrlist))
                cfg += "\n"
                continue
            cfgv4 = ""
            cfgv6 = ""
            want_ipv4 = False
            want_ipv6 = False
            for s in services:
                if cls._name not in s._depends:
                    continue
                ifccfg = s.generatequaggaifcconfig(node,  ifc)
                if s._ipv4_routing:
                    want_ipv4 = True
                if s._ipv6_routing:
                    want_ipv6 = True
                    cfgv6 += ifccfg
                else:
                    cfgv4 += ifccfg
                
            if want_ipv4:
                ipv4list = filter(lambda x: isIPv4Address(x.split('/')[0]),
                                  ifc.addrlist)
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ipv4list))
                cfg += "\n"
                cfg += cfgv4
            if want_ipv6:
                ipv6list = filter(lambda x: isIPv6Address(x.split('/')[0]),
                                  ifc.addrlist)
                cfg += "  "
                cfg += "\n  ".join(map(cls.addrstr, ipv6list))
                cfg += "\n"
                cfg += cfgv6
            cfg += "!\n"
            
        for s in services:
            if cls._name not in s._depends:
                continue
            cfg += s.generatequaggaconfig(node)
        return cfg
    
    @staticmethod
    def addrstr(x):
        ''' helper for mapping IP addresses to zebra config statements
        '''
        if x.find(".") >= 0:
            return "ip address %s" % x
        elif x.find(":") >= 0:
            return "ipv6 address %s" % x
        else:
            raise Value, "invalid address: %s", x
            
    @classmethod
    def generateQuaggaBoot(cls, node, services):
        ''' Generate a shell script used to boot the Quagga daemons.
        '''
        try:
            quagga_bin_search = node.session.cfg['quagga_bin_search']
            quagga_sbin_search = node.session.cfg['quagga_sbin_search']
        except KeyError:
            quagga_bin_search = '"/usr/local/bin /usr/bin /usr/lib/quagga"'
            quagga_sbin_search = '"/usr/local/sbin /usr/sbin /usr/lib/quagga"'
        return """\
#!/bin/sh
# auto-generated by zebra service (quagga.py)
QUAGGA_CONF=%s
QUAGGA_SBIN_SEARCH=%s
QUAGGA_BIN_SEARCH=%s
QUAGGA_STATE_DIR=%s
QUAGGA_USER=%s
QUAGGA_GROUP=%s

searchforprog()
{
    prog=$1
    searchpath=$@
    ret=
    for p in $searchpath; do
        if [ -x $p/$prog ]; then
            ret=$p
            break
        fi
    done
    echo $ret
}

confcheck()
{
    CONF_DIR=`dirname $QUAGGA_CONF`
    # if /etc/quagga exists, point /etc/quagga/Quagga.conf -> CONF_DIR
    if [ "$CONF_DIR" != "/etc/quagga" ] && [ -d /etc/quagga ] && [ ! -e /etc/quagga/Quagga.conf ]; then
        ln -s $CONF_DIR/Quagga.conf /etc/quagga/Quagga.conf
    fi
    # if /etc/quagga exists, point /etc/quagga/vtysh.conf -> CONF_DIR
    if [ "$CONF_DIR" != "/etc/quagga" ] && [ -d /etc/quagga ] && [ ! -e /etc/quagga/vtysh.conf ]; then
        ln -s $CONF_DIR/vtysh.conf /etc/quagga/vtysh.conf
    fi
}

waitforvtyfiles()
{
    for f in "$@"; do
        count=1
        until [ -e $QUAGGA_STATE_DIR/$f ]; do
            if [ $count -eq 10 ]; then
                echo "ERROR: vty file not found: $QUAGGA_STATE_DIR/$f" >&2
                return 1
            fi
            sleep 0.1
            count=$(($count + 1))
        done
    done 
}

bootdaemon()
{
    QUAGGA_SBIN_DIR=$(searchforprog $1 $QUAGGA_SBIN_SEARCH)
    if [ "z$QUAGGA_SBIN_DIR" = "z" ]; then
        echo "ERROR: Quagga's '$1' daemon not found in search path:"
        echo "  $QUAGGA_SBIN_SEARCH"
        return 1
    fi

    flags=""

    if [ "$1" != "zebra" ]; then
        waitforvtyfiles zebra.vty
    fi

    if [ "$1" = "xpimd" ] && \\
        grep -E -q '^[[:space:]]*router[[:space:]]+pim6[[:space:]]*$' $QUAGGA_CONF; then
        flags="$flags -6"
    fi

    $QUAGGA_SBIN_DIR/$1 $flags -u $QUAGGA_USER -g $QUAGGA_GROUP -d
}

bootvtysh()
{
    QUAGGA_BIN_DIR=$(searchforprog $1 $QUAGGA_BIN_SEARCH)
    if [ "z$QUAGGA_BIN_DIR" = "z" ]; then
        echo "ERROR: Quagga's '$1' daemon not found in search path:"
        echo "  $QUAGGA_SBIN_SEARCH"
        return 1
    fi

    vtyfiles="zebra.vty"
    for r in rip ripng ospf6 ospf bgp babel; do
        if grep -q "^router \<${r}\>" $QUAGGA_CONF; then
            vtyfiles="$vtyfiles ${r}d.vty"
        fi
    done

    if grep -E -q '^[[:space:]]*router[[:space:]]+pim6?[[:space:]]*$' $QUAGGA_CONF; then
        vtyfiles="$vtyfiles xpimd.vty"
    fi

    # wait for Quagga daemon vty files to appear before invoking vtysh
    waitforvtyfiles $vtyfiles

    $QUAGGA_BIN_DIR/vtysh -b
}

confcheck
if [ "x$1" = "x" ]; then
    echo "ERROR: missing the name of the Quagga daemon to boot"
    exit 1
elif [ "$1" = "vtysh" ]; then
    bootvtysh $1
else
    bootdaemon $1
fi
""" % (cls._configs[0], quagga_sbin_search, quagga_bin_search, \
       QUAGGA_STATE_DIR, QUAGGA_USER, QUAGGA_GROUP)

addservice(Zebra)

class QuaggaService(CoreService):
    ''' Parent class for Quagga services. Defines properties and methods
        common to Quagga's routing daemons.
    '''
    _name = "QuaggaDaemon"
    _group = "Quagga"
    _depends = ("zebra", )
    _dirs = ()
    _configs = ()
    _startindex = 40
    _startup = ()
    _shutdown = ()
    _meta = "The config file for this service can be found in the Zebra service."
    
    _ipv4_routing = False
    _ipv6_routing = False

    @staticmethod
    def routerid(node):
        ''' Helper to return the first IPv4 address of a node as its router ID.
        '''
        for ifc in node.netifs():
            if hasattr(ifc, 'control') and ifc.control == True:
                continue
            for a in ifc.addrlist:
                if a.find(".") >= 0:
                    return a .split('/') [0]          
        #raise ValueError,  "no IPv4 address found for router ID"
        return "0.0.0.0"
        
    @staticmethod
    def rj45check(ifc):
        ''' Helper to detect whether interface is connected an external RJ45
        link.
        '''
        if ifc.net:
            for peerifc in ifc.net.netifs():
                if peerifc == ifc:
                    continue
                if isinstance(peerifc, nodes.RJ45Node):
                    return True
        return False

    @classmethod
    def generateconfig(cls,  node, filename, services):
        return ""

    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        return ""

    @classmethod
    def generatequaggaconfig(cls,  node):
        return ""



class Ospfv2(QuaggaService):
    ''' The OSPFv2 service provides IPv4 routing for wired networks. It does
        not build its own configuration file but has hooks for adding to the
        unified Quagga.conf file.
    '''
    _name = "OSPFv2"
    _startup = ("sh quaggaboot.sh ospfd",)
    _shutdown = ("killall ospfd", )
    _validate = ("pidof ospfd", )
    _ipv4_routing = True

    @staticmethod
    def mtucheck(ifc):
        ''' Helper to detect MTU mismatch and add the appropriate OSPF
        mtu-ignore command. This is needed when e.g. a node is linked via a
        GreTap device.
        '''
        if ifc.mtu != 1500:
            # a workaround for PhysicalNode GreTap, which has no knowledge of
            # the other nodes/nets
            return "  ip ospf mtu-ignore\n"
        if not ifc.net:
            return ""
        for i in ifc.net.netifs():
            if i.mtu != ifc.mtu:
                return "  ip ospf mtu-ignore\n"
        return ""

    @staticmethod
    def ptpcheck(ifc):
        ''' Helper to detect whether interface is connected to a notional
        point-to-point link.
        '''
        if isinstance(ifc.net, nodes.PtpNet):
            return "  ip ospf network point-to-point\n"
        return ""

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = "router ospf\n"
        rtrid = cls.routerid(node)
        cfg += "  router-id %s\n" % rtrid
        # network 10.0.0.0/24 area 0
        for ifc in node.netifs():
            if hasattr(ifc, 'control') and ifc.control == True:
                continue
            for a in ifc.addrlist:
                if a.find(".") < 0:
                    continue
                net = IPv4Prefix(a)
                cfg += "  network %s area 0\n" % net
        cfg += "!\n"      
        return cfg
        
    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        return cls.mtucheck(ifc)
        #cfg = cls.mtucheck(ifc)
        # external RJ45 connections will use default OSPF timers
        #if cls.rj45check(ifc):
        #    return cfg
        #cfg += cls.ptpcheck(ifc)

        #return cfg + """\
#  ip ospf hello-interval 2
#  ip ospf dead-interval 6
#  ip ospf retransmit-interval 5
#"""
        
addservice(Ospfv2)

class Ospfv3(QuaggaService):
    ''' The OSPFv3 service provides IPv6 routing for wired networks. It does
        not build its own configuration file but has hooks for adding to the
        unified Quagga.conf file.
    '''
    _name = "OSPFv3"
    _startup = ("sh quaggaboot.sh ospf6d",)
    _shutdown = ("killall ospf6d", )
    _validate = ("pidof ospf6d", )
    _ipv4_routing = True
    _ipv6_routing = True

    @staticmethod
    def minmtu(ifc):
        ''' Helper to discover the minimum MTU of interfaces linked with the
        given interface.
        '''
        mtu = ifc.mtu
        if not ifc.net:
            return mtu
        for i in ifc.net.netifs():
            if i.mtu < mtu:
                mtu = i.mtu
        return mtu
        
    @classmethod
    def mtucheck(cls, ifc):
        ''' Helper to detect MTU mismatch and add the appropriate OSPFv3
        ifmtu command. This is needed when e.g. a node is linked via a
        GreTap device.
        '''
        minmtu = cls.minmtu(ifc)
        if minmtu < ifc.mtu:
            return "  ipv6 ospf6 ifmtu %d\n" % minmtu
        else:
            return ""

    @staticmethod
    def ptpcheck(ifc):
        ''' Helper to detect whether interface is connected to a notional
        point-to-point link.
        '''
        if isinstance(ifc.net, nodes.PtpNet):
            return "  ipv6 ospf6 network point-to-point\n"
        return ""

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = "router ospf6\n"
        rtrid = cls.routerid(node)
        cfg += "  router-id %s\n" % rtrid
        for ifc in node.netifs():
            if hasattr(ifc, 'control') and ifc.control == True:
                continue
            cfg += "  interface %s area 0.0.0.0\n" % ifc.name
        cfg += "!\n"
        return cfg
        
    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        return cls.mtucheck(ifc)
        #cfg = cls.mtucheck(ifc)
        # external RJ45 connections will use default OSPF timers
        #if cls.rj45check(ifc):
        #    return cfg
        #cfg += cls.ptpcheck(ifc)

        #return cfg + """\
#  ipv6 ospf6 hello-interval 2
#  ipv6 ospf6 dead-interval 6
#  ipv6 ospf6 retransmit-interval 5
#"""

addservice(Ospfv3)

class Ospfv3mdr(Ospfv3):
    ''' The OSPFv3 MANET Designated Router (MDR) service provides IPv6
        routing for wireless networks. It does not build its own
        configuration file but has hooks for adding to the
        unified Quagga.conf file.
    '''
    _name = "OSPFv3MDR"
    _ipv4_routing = True

    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        cfg = cls.mtucheck(ifc)
        cfg += "  ipv6 ospf6 instance-id 65\n"
        if ifc.net is not None and \
           isinstance(ifc.net, (nodes.WlanNode, nodes.EmaneNode)):
            return cfg + """\
  ipv6 ospf6 hello-interval 2
  ipv6 ospf6 dead-interval 6
  ipv6 ospf6 retransmit-interval 5
  ipv6 ospf6 network manet-designated-router
  ipv6 ospf6 diffhellos
  ipv6 ospf6 adjacencyconnectivity uniconnected
  ipv6 ospf6 lsafullness mincostlsa
"""
        else:
            return cfg

addservice(Ospfv3mdr)

class Bgp(QuaggaService):
    '''' The BGP service provides interdomain routing.
        Peers must be manually configured, with a full mesh for those
        having the same AS number.
    '''
    _name = "BGP"
    _startup = ("sh quaggaboot.sh bgpd",)
    _shutdown = ("killall bgpd", )
    _validate = ("pidof bgpd", )
    _custom_needed = True
    _ipv4_routing = True
    _ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = "!\n! BGP configuration\n!\n"
        cfg += "! You should configure the AS number below,\n"
        cfg += "! along with this router's peers.\n!\n"
        cfg += "router bgp %s\n" % node.objid
        rtrid = cls.routerid(node)
        cfg += "  bgp router-id %s\n" % rtrid
        cfg += "  redistribute connected\n"
        cfg += "! neighbor 1.2.3.4 remote-as 555\n!\n"
        return cfg

addservice(Bgp)

class Rip(QuaggaService):
    ''' The RIP service provides IPv4 routing for wired networks.
    '''
    _name = "RIP"
    _startup = ("sh quaggaboot.sh ripd",)
    _shutdown = ("killall ripd", )
    _validate = ("pidof ripd", )
    _ipv4_routing = True

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = """\
router rip
  redistribute static
  redistribute connected
  redistribute ospf
  network 0.0.0.0/0
!
"""
        return cfg

addservice(Rip)

class Ripng(QuaggaService):
    ''' The RIP NG service provides IPv6 routing for wired networks.
    '''
    _name = "RIPNG"
    _startup = ("sh quaggaboot.sh ripngd",)
    _shutdown = ("killall ripngd", )
    _validate = ("pidof ripngd", )
    _ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = """\
router ripng
  redistribute static
  redistribute connected
  redistribute ospf6
  network ::/0
!
"""
        return cfg

addservice(Ripng)

class Babel(QuaggaService):
    ''' The Babel service provides a loop-avoiding distance-vector routing 
    protocol for IPv6 and IPv4 with fast convergence properties.
    '''
    _name = "Babel"
    _startup = ("sh quaggaboot.sh babeld",)
    _shutdown = ("killall babeld", )
    _validate = ("pidof babeld", )
    _ipv6_routing = True

    @classmethod
    def generatequaggaconfig(cls,  node):
        cfg = "router babel\n"
        for ifc in node.netifs():
            if hasattr(ifc, 'control') and ifc.control == True:
                continue
            cfg += "  network %s\n" % ifc.name
        cfg += "  redistribute static\n  redistribute connected\n"
        return cfg
        
    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        type = "wired"
        if ifc.net and ifc.net.linktype == coreapi.CORE_LINK_WIRELESS:
            return "  babel wireless\n  no babel split-horizon\n"
        else:
            return "  babel wired\n  babel split-horizon\n"

addservice(Babel)

class Xpimd(QuaggaService):
    '''\
    PIM multicast routing based on XORP.
    '''
    _name = 'Xpimd'
    _startup = ('sh quaggaboot.sh xpimd',)
    _shutdown = ('killall xpimd', )
    _validate = ('pidof xpimd', )
    _ipv4_routing = True

    @classmethod
    def generatequaggaconfig(cls,  node):
        ifname = 'eth0'
        for ifc in node.netifs():
            if ifc.name != 'lo':
                ifname = ifc.name
                break
        cfg = 'router mfea\n!\n'
        cfg += 'router pim\n'
        cfg += '  !ip pim rp-address 10.0.0.1\n'
        cfg += '  ip pim bsr-candidate %s\n' % ifname
        cfg += '  ip pim rp-candidate %s\n' % ifname
        cfg += '  !ip pim spt-threshold interval 10 bytes 80000\n'
        return cfg

    @classmethod
    def generatequaggaifcconfig(cls,  node,  ifc):
        return '  ip mfea\n  ip igmp\n  ip pim\n'

addservice(Xpimd)

class Vtysh(CoreService):
    ''' Simple service to run vtysh -b (boot) after all Quagga daemons have
        started.
    '''
    _name = "vtysh"
    _group = "Quagga"
    _startindex = 45
    _startup = ("sh quaggaboot.sh vtysh",)
    _shutdown = ()

    @classmethod
    def generateconfig(cls, node, filename, services):
        return ""

addservice(Vtysh)


