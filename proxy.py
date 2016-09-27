#!/usr/bin/env python 

# Jason Steck
# Spring 15
#   This program creates a proxy that serves  
# GET requests and can cache page requests.

#import threading
import urlparse
import socket 
import time
import sys
import os

from multiprocessing import Process, Manager, Lock

# Variables
debug = 0
traffic = 0
cacheDir = 'ProxyCache/'
expirationTime = 60 # In seconds
linebreak = '\r\n'
# ----------------------------------

# Simple method for outputting only when we're in debug mode
def d(msg):
	global debug
	if debug:
		print msg

# Used on places
def printTraffic(msg):
	global traffic
	if(traffic):
		print msg

# Custom exceptions for handling requests
class BadRequest(Exception):
    pass

# The custom exception thrown when a request type other than get is given
class NotImplemented(Exception):
	pass

#   Acts as the interface between clients and their destinations.
# This class will serve up the cached version of the webpage if
# there is one, otherwise it will fetch the actual page.
class targetCacheSocket:
	cache = None
	host = None
	port = None
	ts = None
	cs = None
	sendTo = None
	cacheName = None
	def __init__(self, cs, host, port, absoluteURI):
		self.cs = cs
		# Get the name of the file the cache might be stored in
		cacheName = cacheDir + absoluteURI.replace('/','_').lower()
		self.cacheName = cacheName

		# Attempt to load cache
		d("Looking for cache: '"+cacheName+"'")
		if(os.path.isfile(cacheName)):
			#Check if the cache has expired
			age = time.time() - os.path.getmtime(cacheName)
			d("Age: "+str(age))
			# If the file is not older than the allowed amout
			if(age<expirationTime):
				print "Cache found: "+cacheName
				cfile = None
				try:
					# Load the cached data from file
					cfile = open(cacheName)
					self.cache = cfile.read()
					d("Successfully read from cache: '"+self.cache+"'")
				except Exception as e:
					d("Error reading cache: " + str(e))
				finally:
					d("Closing file")
					# If something goes wrong, close the file
					if cfile!=None:
						cfile.close()
		else:
			print "Cache not found"
		# If we didn't find it then leave cache as None

		self.host = host
		self.port = port
		if self.cache!=None:
			# send all data to no where since we don't care about the rest of the client request
			self.sendTo = self.sendNoWhere
		else:
			# load the socket as normal
			self.sendTo = self.actualSend
			print 'Connect to target host: "'+self.host+'" on port: "'+str(self.port)+'"'
			try:
				self.ts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				self.ts.connect((self.host,self.port))
			except:
				badReq(self.cs,'Error connecting to "'+self.host+'" by port "'+str(self.port)+'"')
				return
			# begin listening
			Process(target=self.listenForward).start()

	def sendNoWhere(self, msg):
		d("Data sent to nowhere because we're cached")

	def actualSend(self, msg):
		d("Actually sending the data.")
		send(self.ts, msg)

	def saveCache(self, data):
		d("Saving cache")
		# If the cache directory doesn't exist, then create it
		if not os.path.exists(cacheDir):
			os.makedirs(cacheDir)
		# Safe the cache contents to file
		f = None
		try:
			f = open(self.cacheName, 'w')
			f.write(data)
			d("Successfully saved cache")
		except Exception as e:
			d("Error saving cache: "+str(e))
		finally:
			if f!=None:
				f.close()
		

	def trySendCache(self):
		if(self.cache):
			send(self.cs, self.cache)


	#   Keeps a connection open to the target and simply forwards
	# everything it receives to the client
	def listenForward(self):
		totalData = ''
		data = 'x'
		try:
			while data!='':
				data = self.ts.recv(size)
				send(self.cs, data)
				printTraffic('  Data from target:\r\n"'+data+"\"")
				totalData += data
			d('Connection with target terminated')
			disconnect(self.ts)
			disconnect(self.cs)
			# Save cache
			self.saveCache(totalData)
		except:
			return # do nothing besides ending the loop



class Client:

	# holds all the data that still needs to be sent to the target (once it's identified)
	tosend = ''
	# Filters the line comming in from the client
	filter = None
	tcs = None
	cs = None

	""" Holds a socket connection for either the client or target """
	def __init__(self, cs, address):
		self.cs = cs
		self.handle(address)



	# The actual heavy lifting done with each connection
	def handle(self, address):
		print 'Incoming connection from '+ str(address)+'\r\n'

		# wrap everything in a class for variable isolation
		linecdata=''

		self.filter = self.lookingForReqFilter
		#self.filter = None
		buff = clientBuffer

		cdata = self.cs.recv(size)
		while(cdata!=''):
			# cdata = cdata.replace('\r\n','\\r\\n\r\n') # make \r\n visible
			write(cdata)
			linecdata+=cdata
			# Search for any breakpoints
			foundLines, linecdata = buff(linecdata)

			# -- Apply client request checks --
			# if first line, check request type, extract target
			d("Starting filter check...")
			if(foundLines!=None):
				split = foundLines.split(linebreak)
				
				x = 0
				while x<len(split) :
					d("Reading, split["+str(x)+"]: "+str(split[x]))
					if(self.filter!=None):
						try:
							res = self.filter(split[x])
							d("Done with filter")
							if(res==None):
								# delete the entry
								d("REMOVING, split["+str(x)+"]: "+str(split[x]))
								split.remove(split[x])
								x -= 1
							else:
								split[x] = res
						except BadRequest as e:
							badReq(self.cs, e)
						except NotImplemented as e:
							notImpl(self.cs, e)
					x+=1
				foundLines = linebreak.join(split)
			printTraffic("Done with filter, result: "+foundLines)

			# -- Send to target (if it exists) --
			# add to things to send
			if(foundLines!=None and self.tcs!=None):
				self.tosend += foundLines
				printTraffic("Sending to target: \""+self.tosend+"\"----")
				if(self.tcs.sendTo):
					self.tcs.sendTo(self.tosend)
					# No need to send that data again
					self.tosend = '';

			# Get more data if we can
			try:
				cdata = self.cs.recv(size)
			except:
				break

		d('Done, closing connections...')
		# Make sure the sockets are closed
		if(self.tcs and self.tcs.ts):
			disconnect(self.tcs.ts)
		if(self.cs):
			disconnect(self.cs)
		d('Sockets closed.')

	# Used to search for and parse the request line
	def lookingForReqFilter(self, foundLine):
		port = None
		host = None

		if(foundLine==''):
			return foundLine

		split = foundLine.split(' ')
		if(len(split)!=3):
			raise BadRequest("Looking for a 'GET' Request line with 3 sections, <METHOD> <URL> <HTTP VERSION> but found: '"+', '.join(split)+"'")

		if(split[0].lower()!='get'):
		 	raise NotImplemented("Request '"+split[0]+"' is not implemented")

		httpVer = split[2].lower()
		if(httpVer!='http/1.0' and httpVer!='http/1.1'):
			raise NotImplemented("Request version '"+split[2]+"' is nov valid.")

		#Verify absolut URI
		if not is_absolute(split[1]):
			raise BadRequest("Proxy server requires an absolute URI but instead got '"+split[1]+"'")

		#Split absolute URI
		url = split[1]
		if(url.lower().startswith('http://')):
			port = 80
			url = url[7:]
		elif(url.startswith('//')):
			url = url[2:]

		# Save absolute URI
		absoluteURI = url

		# pull port if any
		colon = url.find(':')
		if(colon>0):
			port = int(url[colon+1:])
			url = url[:colon]

		# extract the host
		slash = url.find('/')
		if(slash>=0):
			host = url[:slash]
			url = url[slash:]
		else:
			host = url
			url = '/'

		if(port==None):
			port = 80

		# Configure the relative URI and host header we will be using
		split[1] = url
		reqLine = ' '.join(split)
		addon = ''
		if(port!=80):
			addon = ':'+str(port)
		reqLine += '\r\nHost: '+host+addon

		# Setup abstract target (might be real, might be cache)
		self.tcs = targetCacheSocket(self.cs, host, port, absoluteURI)

		self.filter = self.verifyingHeadersFilter
		return reqLine

	# The other filter, used to verify validity of the headers
	def verifyingHeadersFilter(self, foundLine):
		if(foundLine==''):
			# If we have a cached version of the page header, try to send it to the client now
			self.tcs.trySendCache()
			# Switch back to looking for GET requests
			self.filter = self.lookingForReqFilter
			return "Connection: close\r\n"

		split = foundLine.split(': ')
		if(len(split)!=2):
			raise BadRequest("Header line incorrect: '"+', '.join(split)+"'")
		elif(split[0].lower()=='connection'): # filter out "Connection" headers since we put our own in
			return None
		elif(split[0].lower()=='host'): # filter out "Host" headers since we derive our own from the absolute URI
			return None

		return foundLine # if everything went fine, do this simple return

# ------------------------ End of Classes ---------------------------

# Wraps each of the connections and gracefully catches errors
def connectionMade(cs, address):

	try:
		Client(cs, address)
	except:  #Thrown when the user presses Ctrl+c
		print 'Error with connection.'
	    
	disconnect(cs)

# This determines when to release the client's incoming request
# Only once we've found a linebreak (\r\n) will we give that section out
def clientBuffer(linecdata):
	found = linecdata.rfind(linebreak)
	split = found+len(linebreak)
	if found>=0:
		return linecdata[:split], linecdata[split:]
	else:
		return None, linecdata


# Used for determining if a URL is absolute (includes "//www.google.com")
def is_absolute(url):
	return bool(urlparse.urlparse(url).netloc)

# Simple message writing without the newline
def write(msg):
	sys.stdout.write(msg)

# Method for continually receiving data from the provided socket until it is terminated
def receive(s):
    data = ''
    totalData = ''
    # Make sure we keep receiving until we get the end signal
    while 1:
        data = s.recv(size)
        printTraffic('  Data received:\r\n"'+data+'"')
        if data=='':
            print '  Connection lost' # This happens when the connection is lost
            break
        totalData += data

    return totalData

# Makes sure the message is sent along the socket
def send(s, msg):
    totalSent = 0
    # Make sure we've sent everything
    while totalSent < len(msg):
        sent = s.send(msg[totalSent:])
        if sent == 0:
            raise RuntimeError("Socket connection broken.")
        totalSent = totalSent + sent

# When called, it returns the "Bad Request" page to the client due to a malformed request
def badReq(s,msg):
    print 'Bad request: ', msg
    bad = 'HTTP/1.1 400 Bad Request\r\nContent-Length: 230\r\nConnection: close\r\nContent-Type: text/html; charset=iso-8859-1\r\n\r\n<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">\r\n<html><head>\r\n<title>400 Bad Request</title>\r\n</head><body>\r\n<h1>Bad Request</h1>\r\n<p>Your browser sent a request that this server could not understand.<br />\r\n</p>\r\n</body></html>\r\n'
    send(s,bad)
    disconnect(s)

# Sends the "Not Implemented" page if the client tries to use a method other than GET
def notImpl(s,msg):
    print 'Request Not Implemented: ', msg
    bad = 'HTTP/1.1 501 Not Implemented\r\nContent-Length: 234\r\nConnection: close\r\nContent-Type: text/html; charset=iso-8859-1\r\n\r\n<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">\r\n<html><head>\r\n<title>501 Not Implemented</title>\r\n</head><body>\r\n<h1>Not Implemented</h1>\r\n<p>Your browser sent a request that this server could not handle.<br />\r\n</p>\r\n</body></html>\r\n'
    send(s,bad)
    disconnect(s)


# Quietly disconnects the socket
def disconnect(s):
    try:
        s.shutdown(socket.SHUT_RDWR)
        s.close()
        return True
    except:
        return False   


# ----------------------------------
host = ''
port = 67878 # default port
backlog = 50
size = 4096

# See if the port was passed in the arguments
if len(sys.argv)>1 and str.isdigit(sys.argv[1]):
    pars = int(sys.argv[1])
    if pars>0:
        port = pars
else:
    print 'usage: python '+sys.argv[0].split('/')[-1]+' <port>'

# Bind the primary socket for clients to contact
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind((host,port))
except:
    print 'Error: Port already in use.'
    sys.exit()
s.listen(backlog)

print 'Proxy IP: ', socket.gethostbyname(socket.gethostname())
print 'Listening on port: ',port
print '<press Ctrl+c to end>\r\n'
try: 
    #Keep listening for connections
    while 1:
        print 'Waiting for connection...'
        client, address = s.accept()
        # Handle each connection in its own thread
        Process(target=connectionMade, args=(client,address)).start()

except KeyboardInterrupt:  #Thrown when the user presses Ctrl+c
    print '\r\nShutting down the web server'
    s.shutdown(socket.SHUT_RDWR)
    s.close()