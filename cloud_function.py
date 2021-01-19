import json
import re
import base64
import subprocess

from google.cloud import storage
from google.cloud import vision
from google.cloud import texttospeech


storage_client = storage.Client()
vision_client = vision.ImageAnnotatorClient()
tts_client = texttospeech.TextToSpeechClient()

def pdf_ts(event, context):
	"""Triggered by a change to a Cloud Storage bucket.
	Args:
		 event (dict): Event payload.
		 context (google.cloud.functions.Context): Metadata for the event.
	"""
	# Get the filename that has been uploaded to GCS
	bucket_name = event['bucket']
	name = event['name']

	if name.lower().endswith(".pdf"):
		gcs_source_uri = 'gs://{}/{}'.format(bucket_name,name)
		gcs_destination_uri = re.match(r'(gs://.+)\..+', gcs_source_uri).group(1) + "_text" #is correct
		pdf_tt(gcs_source_uri,gcs_destination_uri)   
		return

	if name.lower().endswith(".txt"):
		split_strings=[]

		bucket = storage_client.get_bucket(bucket_name)
		file_blob = bucket.get_blob(name)

		text = file_blob.download_as_string().decode("utf-8")
		print(text[0:100])

		n = 3000

		m = len(text)//n
		for i in range(0,m*n,n):
			split_strings.append(text[i : i + n])
		split_strings.append(text[m*n : len(text)-1])
		print("Text has been separated to {} parts".format(i//n+1))
		for i in range(len(split_strings)):
			tts(bucket,split_strings[i] , re.match(r'(.+)\..+', name).group(1)+str(i+1))



		

def pdf_tt(gcs_source_uri,gcs_destination_uri):
	# Supported mime_types are: 'application/pdf' and 'image/tiff'
	mime_type = 'application/pdf'
	
	# How many pages should be grouped into each json output file.
	batch_size = 1
	
	
	
	feature = vision.Feature(
			type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
	
	gcs_source = vision.GcsSource(uri=gcs_source_uri)
	input_config = vision.InputConfig(
			gcs_source=gcs_source, mime_type=mime_type)
	
	gcs_destination = vision.GcsDestination(uri=gcs_destination_uri)
	output_config = vision.OutputConfig(
			gcs_destination=gcs_destination, batch_size=batch_size)
	
	
	async_request = vision.AsyncAnnotateFileRequest(
			features=[feature], input_config=input_config,
			output_config=output_config)
	
	operation = vision_client.async_batch_annotate_files(
			requests=[async_request])
	
	print('Waiting for the operation to finish.')
	operation.result(timeout=420)
	
	# Once the request has completed and the output has been
	# written to GCS, we can list all the output files.
	
	match = re.match(r'gs://([^/]+)/(.+)', gcs_destination_uri)

	bucket_name = match.group(1)
	prefix = match.group(2)
	
	bucket = storage_client.get_bucket(bucket_name)
	
	# List objects with the given prefix.
	blob_list = list(bucket.list_blobs(prefix=prefix))

	# Process the first output file from GCS.

	"""
	with open("temp.txt", "w+") as file_obj: 
		for i in range(len(blob_list)):
			response = json.loads(blob_list[i].download_as_string()) 
			file_obj.write(blob_list[i].name+"\n")
			#print(blob_list[i].name+"\n")
			file_obj.write(response['responses'][0]['fullTextAnnotation']['text']) 

			#Don't write to text file on cloud!
	"""

	unfiltered_content = ""

	for i in range(len(blob_list)):
		response = json.loads(blob_list[i].download_as_string()) 
		unfiltered_content += blob_list[i].name
		unfiltered_content += "\n"
		#print(blob_list[i].name+"\n")
		unfiltered_content += (response['responses'][0]['fullTextAnnotation']['text']) 


	regex = r"{}output-(\d{{1,2}})-to-(\d{{1,2}})\.json".format(prefix)
	
	matches = re.finditer(regex,unfiltered_content,re.MULTILINE)
	sequence = {}
	flag = 0
	for match in matches:
		if (match.group(1) == match.group(2)):
			sequence[match.group(1)] = flag #sequence[i] is the false page num while i is the real page num
		flag += 1
	
	pages = []
	for i in sequence: 
		pages.append(int(i))
	page_num = max(pages)


	regex2 = r"{}output-\d{{1,2}}-to-\d{{1,2}}\.json".format(prefix)
	split_content = re.split(regex2,unfiltered_content)[1:] 
	
	true_content = []
	
	for j in range(page_num):
		true_content.append(split_content[ int( sequence[str(j+1)] ) ])
	
	

	content = '\n'.join(true_content) 

	#write content to storage bucket
	text_output = bucket.blob( "{}.txt".format(prefix) )	 #input filename
	text_output.upload_from_string(content)


def tts(bucket,text,prefix):
	# Set the text input to be synthesized
	synthesis_input = texttospeech.SynthesisInput(text=text)
	# Build the voice request, select the language code ("en-US") and the ssml
	# voice gender ("neutral")
	voice = texttospeech.VoiceSelectionParams(
	    language_code="yue-HK", ssml_gender=texttospeech.SsmlVoiceGender.MALE
	)
	
	# Select the type of audio file you want returned
	audio_config = texttospeech.AudioConfig(
	    audio_encoding=texttospeech.AudioEncoding.MP3
	)
	
	# Perform the text-to-speech request on the text input with the selected
	# voice parameters and audio file type
	response = tts_client.synthesize_speech(
	    input=synthesis_input, voice=voice, audio_config=audio_config
	)

	#write content to storage bucket
	output = bucket.blob( "{}.mp3".format(prefix))	 #input filename
	output.upload_from_string(response.audio_content)
	print('Audio content written to file "output.mp3"')	


"""

def tts(bucket,text,prefix):
	request = { #write the request file 
		"input" : {
			"text" : text 
		},
		"voice" : {
			"languageCode": "yue-HK",
			"name": "yue-HK-Standard-B",
			"ssmlGender": "MALE"
		},		
		"audioConfig" : {
			"audioEncoding": "MP3"
		}
	}
	
	
	print('Passing text to Google cloud TTS.')
	print("Text:", text[0:100])

	out = subprocess.run(["curl -X POST -H \"Authorization: Bearer \"$(gcloud auth application-default print-access-token) -H \"Content-Type: application/json; charset=utf-8\" -d {} https://texttospeech.googleapis.com/v1/text:synthesize".format(request)],bufsize = -1,shell = True,capture_output=True)
	text_output = str(getattr(out,'stdout'))
	text_output = text_output.replace(r"\n" , "").replace("b'", "'")[1:-1]
	#Here, text_output should be a json. I should be able to load a str instead of file

	
	#out = json.load(text_output) << if without this TypeError: string indices must be integers 
	# with this AttributeError: 'str' object has no attribute 'read' 
	out = json.loads(text_output)
	print(type(out))
	print(out)
	audio = out["audioContent"] #text_output is still string 
	print("Audio:", audio[0:100])
	decoded = base64.standard_b64decode(audio)

	
	#write content to storage bucket
	text_output = bucket.blob( "{}.mp3".format(prefix))	 #input filename
	text_output.upload_from_string(decoded)	"""





