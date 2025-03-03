'''
Usage: gepo [METHOD] [OPTIONS] URL [DATA]

Send HTTP requests from the command line with ease.

Arguments:
  METHOD                      HTTP method (GET, POST, PUT, DELETE, etc.) [default: GET]
  URL                         URL to send the request to [required]
  DATA                        Optional inline data for request body

Basic Options:
  -h, --help                  Show this help message and exit
  --save PATH                 Save response to file
  --file PATH                 Use data from file for request body
  --json                      Use JSON format (Content-Type: application/json)
  --html                      Use HTML format (Content-Type: text/html)
  --xml                       Use XML format (Content-Type: application/xml)
  --text, --plain             Use plain text (Content-Type: text/plain)
  --form                      Send data as form-urlencoded
  --multipart                 Send data as multipart/form-data (for file uploads)
  
Request Options:
  --header, -H HEADER         Add custom header (format: 'Name: Value')
  --query, -q QUERY           Add URL query parameter (format: 'name=value')
  --timeout TIMEOUT           Request timeout in seconds [default: 30]
  --auth AUTH                 Authentication credentials (format: 'username:password' or token)
  --auth-type {basic,digest,bearer}
                              Authentication type [default: basic]
  --no-verify                 Disable SSL certificate verification
  --proxy PROXY               Use proxy server (e.g., http://proxy.example.com:8080)
  --max-redirects N           Maximum redirects to follow [default: 5]
  --http-version {1.0,1.1,2}  HTTP version to use
  --cookie COOKIE             Set cookie (format: 'name=value')
  
Output Options:
  --output-format {text,json,auto}
                              Response output format [default: auto]
  --encoding ENCODING         Character encoding for response [default: utf-8]
  --verbose, -v               Enable verbose output
  --stream                    Stream response for large files

Examples:
  gepo GET https://api.example.com/users
  gepo POST https://api.example.com/users --json '{"name":"John"}'
  gepo https://example.com/form --form "name=John&email=john@example.com"
  gepo POST https://api.example.com/upload --file image.jpg --multipart

For more information and examples, run: gepo --help
'''


#!/usr/bin/env python3
import argparse
import os
import sys
import json
import requests
import urllib.parse
from typing import Dict, Optional, Any, List, Tuple, Union
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
import mimetypes
import time


def parse_arguments():
    """Parse command line arguments for gepo with comprehensive options and sensible defaults."""
    parser = argparse.ArgumentParser(description="Send HTTP requests from the command line")
    
    # First argument is always the method, default to GET if not provided
    parser.add_argument("method", nargs="?", default="GET", help="HTTP method (GET, POST, PUT, DELETE, etc.)")
    
    # Options
    parser.add_argument("--save", metavar="PATH", help="Save response to file at specified path")
    parser.add_argument("--file", metavar="PATH", help="Use data from file for request body")
    parser.add_argument("--json", action="store_true", help="Set Content-Type to application/json")
    parser.add_argument("--html", action="store_true", help="Set Content-Type to text/html")
    parser.add_argument("--xml", action="store_true", help="Set Content-Type to application/xml")
    parser.add_argument("--text", "--plain", action="store_true", help="Set Content-Type to text/plain")
    parser.add_argument("--form", action="store_true", help="Send data as form-urlencoded")
    parser.add_argument("--multipart", action="store_true", help="Send data as multipart/form-data")
    
    # Advanced options
    parser.add_argument("--header", "-H", action="append", help="Custom header in format 'Name: Value'")
    parser.add_argument("--query", "-q", action="append", help="URL query parameter in format 'name=value'")
    parser.add_argument("--timeout", type=float, default=30, help="Request timeout in seconds")
    parser.add_argument("--auth", help="Basic auth credentials in format 'username:password'")
    parser.add_argument("--auth-type", choices=["basic", "digest", "bearer"], default="basic", 
                        help="Authentication type")
    parser.add_argument("--no-verify", action="store_true", help="Disable SSL certificate verification")
    parser.add_argument("--proxy", help="Use proxy server (e.g., http://proxy.example.com:8080)")
    parser.add_argument("--max-redirects", type=int, default=5, help="Maximum number of redirects to follow")
    parser.add_argument("--http-version", choices=["1.0", "1.1", "2"], help="HTTP version to use")
    parser.add_argument("--cookie", action="append", help="Set cookies in format 'name=value'")
    parser.add_argument("--output-format", choices=["text", "json", "auto"], default="auto", 
                        help="Response output format")
    parser.add_argument("--encoding", default="utf-8", help="Character encoding for response")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--stream", action="store_true", help="Stream response for large files")
    
    # URL is a positional argument, required unless reading from stdin
    parser.add_argument("url", nargs="?", help="URL to send the request to")
    
    # Optional inline data
    parser.add_argument("data", nargs="?", help="Inline data for request body")
    
    # Parse known args
    args, unknown = parser.parse_known_args()
    
    # Check for URL - it's required unless we're reading from stdin
    if not args.url:
        if not sys.stdin.isatty():
            # Can read URL from stdin
            args.url = sys.stdin.read().strip()
        else:
            parser.error("URL is required (unless piping input)")
    
    # Check for conflicting options
    content_type_flags = [args.json, args.html, args.xml, args.text, args.form, args.multipart]
    if sum(flag is True for flag in content_type_flags) > 1:
        parser.error("Multiple content type flags specified. Use only one of --json, --html, --xml, --text, --form, or --multipart")
    
    if args.file and args.data:
        parser.error("Cannot use both inline data and --file flag")
    
    # Auto-detect content type from data or file if no flag is given
    if args.data and not any(content_type_flags):
        # Try to auto-detect if it's JSON
        try:
            json.loads(args.data)
            args.json = True
        except (json.JSONDecodeError, TypeError):
            # If data contains form-like content with = and &, assume form data
            if isinstance(args.data, str) and "=" in args.data and "&" in args.data:
                args.form = True
            else:
                # Default to text
                args.text = True
    
    # Auto-detect content type from file extension if using file
    if args.file and not any(content_type_flags):
        mime_type = detect_file_type(args.file)
        if mime_type:
            if mime_type.startswith("application/json"):
                args.json = True
            elif mime_type.startswith("text/html"):
                args.html = True
            elif mime_type.startswith("application/xml") or mime_type.startswith("text/xml"):
                args.xml = True
            elif mime_type.startswith("text/plain"):
                args.text = True
            elif mime_type.startswith("multipart/form-data"):
                args.multipart = True
            elif mime_type.startswith("application/x-www-form-urlencoded"):
                args.form = True
    
    return args


def validate_url(url: str) -> str:
    """Validate and normalize URL."""
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'http://' + url
    
    try:
        result = urllib.parse.urlparse(url)
        return url if all([result.scheme, result.netloc]) else None
    except Exception:
        return None


def parse_auth(auth_string: str, auth_type: str) -> Tuple[Any, Dict[str, str]]:
    """Parse authentication information."""
    auth_obj = None
    auth_headers = {}
    
    if not auth_string:
        return auth_obj, auth_headers
    
    if auth_type == "bearer":
        auth_headers["Authorization"] = f"Bearer {auth_string}"
    elif ":" in auth_string and auth_type in ["basic", "digest"]:
        username, password = auth_string.split(":", 1)
        if auth_type == "basic":
            auth_obj = HTTPBasicAuth(username, password)
        elif auth_type == "digest":
            auth_obj = HTTPDigestAuth(username, password)
    
    return auth_obj, auth_headers


def parse_headers(header_strings: List[str]) -> Dict[str, str]:
    """Parse header strings into a dictionary."""
    headers = {}
    
    if not header_strings:
        return headers
    
    for header in header_strings:
        if ":" in header:
            key, value = header.split(":", 1)
            headers[key.strip()] = value.strip()
        else:
            print(f"Warning: Ignoring malformed header: {header}")
    
    return headers


def parse_cookies(cookie_strings: List[str]) -> Dict[str, str]:
    """Parse cookie strings into a dictionary."""
    cookies = {}
    
    if not cookie_strings:
        return cookies
    
    for cookie in cookie_strings:
        if "=" in cookie:
            key, value = cookie.split("=", 1)
            cookies[key.strip()] = value.strip()
        else:
            print(f"Warning: Ignoring malformed cookie: {cookie}")
    
    return cookies


def parse_query_params(query_strings: List[str]) -> Dict[str, str]:
    """Parse query parameter strings."""
    params = {}
    
    if not query_strings:
        return params
    
    for query in query_strings:
        if "=" in query:
            key, value = query.split("=", 1)
            params[key.strip()] = value.strip()
        else:
            params[query.strip()] = ""
    
    return params


def detect_file_type(file_path: str) -> str:
    """Detect file MIME type."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def read_file_data(file_path: str, binary: bool = False) -> Union[str, bytes]:
    """Read data from a file, with option for binary mode."""
    try:
        mode = 'rb' if binary else 'r'
        with open(file_path, mode) as file:
            return file.read()
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied when reading file: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        sys.exit(1)


def save_response(response_data: Union[str, bytes], save_path: str, binary: bool = False) -> None:
    """Save the response to a file, with option for binary mode."""
    try:
        # Ensure directory exists
        directory = os.path.dirname(os.path.abspath(save_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        
        mode = 'wb' if binary else 'w'
        with open(save_path, mode) as file:
            file.write(response_data)
        print(f"Response saved to {save_path}")
    except PermissionError:
        print(f"Error: Permission denied when writing to file: {save_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error saving response: {str(e)}")
        sys.exit(1)


def prepare_request_data(args) -> Tuple[Union[str, Dict, bytes, None], Dict[str, str], bool]:
    """Prepare request data and headers based on content type and source."""
    headers = {}
    data = None
    is_binary = False
    
    # Determine content type
    if args.json:
        headers["Content-Type"] = "application/json"
    elif args.html:
        headers["Content-Type"] = "text/html"
    elif args.xml:
        headers["Content-Type"] = "application/xml"
    elif args.text:
        headers["Content-Type"] = "text/plain"
    elif args.form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif args.multipart:
        # Don't set Content-Type for multipart as requests will set it with boundary
        pass
    
    # Get data from file or inline
    if args.file:
        # Determine if we need binary mode based on content type or file extension
        file_mime = detect_file_type(args.file)
        is_binary = not file_mime.startswith(('text/', 'application/json', 'application/xml'))
        
        if not args.multipart:
            # For regular requests, just read the file
            data = read_file_data(args.file, binary=is_binary)
            
            # If no content type was specified but we're reading a file, try to infer it
            if not any([args.json, args.html, args.xml, args.text, args.form]) and file_mime:
                headers["Content-Type"] = file_mime
        else:
            # For multipart requests, we'll handle file preparation in send_request
            data = args.file
    elif args.data:
        data = args.data
        
        # If sending JSON data, try to parse it to ensure it's valid
        if args.json and isinstance(data, str):
            try:
                json.loads(data)
            except json.JSONDecodeError:
                print("Warning: Provided JSON data doesn't appear to be valid")
    
    # Handle form data parsing
    if args.form and isinstance(data, str) and not is_binary:
        try:
            # Convert form data string to dict if it looks like key=value&key2=value2
            if "=" in data and "&" in data:
                form_dict = {}
                for pair in data.split("&"):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        form_dict[key] = value
                    else:
                        form_dict[pair] = ""
                data = form_dict
        except Exception as e:
            print(f"Warning: Error parsing form data: {str(e)}")
    
    return data, headers, is_binary


def format_response(response, args):
    """Format the response according to output preferences."""
    # Auto-detect response format if set to auto
    if args.output_format == "auto":
        if response.headers.get("Content-Type", "").startswith("application/json"):
            try:
                return json.dumps(response.json(), indent=2)
            except json.JSONDecodeError:
                return response.text
        else:
            return response.text
    elif args.output_format == "json":
        try:
            return json.dumps(response.json(), indent=2)
        except json.JSONDecodeError:
            print("Warning: Response claimed to be JSON but couldn't be parsed")
            return response.text
    else:
        return response.text


def send_request(args) -> None:
    """Send the HTTP request based on parsed arguments."""
    # Validate URL
    validated_url = validate_url(args.url)
    if not validated_url:
        print(f"Error: Invalid URL: {args.url}")
        sys.exit(1)
    
    # Prepare authentication
    auth, auth_headers = parse_auth(args.auth, args.auth_type)
    
    # Prepare headers
    headers = {}
    if args.header:
        headers.update(parse_headers(args.header))
    
    # Parse cookies
    cookies = parse_cookies(args.cookie) if args.cookie else None
    
    # Parse query parameters
    params = parse_query_params(args.query) if args.query else None
    
    # Prepare request data and content type headers
    data, content_headers, is_binary = prepare_request_data(args)
    headers.update(content_headers)
    headers.update(auth_headers)
    
    # Prepare session with proxy settings if needed
    session = requests.Session()
    if args.proxy:
        session.proxies = {
            "http": args.proxy,
            "https": args.proxy
        }
    
    # Set SSL verification
    verify = not args.no_verify
    
    # Set redirect behavior
    allow_redirects = True
    max_redirects = args.max_redirects if args.max_redirects >= 0 else None
    if max_redirects is not None:
        session.max_redirects = max_redirects
    
    # Prepare kwargs for request
    kwargs = {
        "url": validated_url,
        "headers": headers,
        "cookies": cookies,
        "params": params,
        "timeout": args.timeout,
        "verify": verify,
        "allow_redirects": allow_redirects,
        "auth": auth
    }
    
    # Set HTTP version if specified
    if args.http_version:
        if args.http_version == "2":
            # For HTTP/2, we need to use the requests-http2 library which is not included by default
            print("Warning: HTTP/2 support requires the requests-http2 library, falling back to HTTP/1.1")
        else:
            # HTTP/1.0 or HTTP/1.1
            kwargs["http_version"] = args.http_version
    
    # Handle special case for multipart form data with file upload
    if args.multipart and args.file:
        with open(args.file, 'rb') as f:
            filename = os.path.basename(args.file)
            mime_type = detect_file_type(args.file)
            files = {'file': (filename, f, mime_type)}
            kwargs["files"] = files
    else:
        kwargs["data"] = data
    
    # Normalize HTTP method (case-insensitive)
    method = args.method.upper()
    
    # Auto-detect appropriate method based on data presence if not explicitly overridden
    if method == "GET" and (data or args.file) and not args.method:
        # If data is provided but no explicit method, assume POST
        method = "POST"
        print("Notice: Automatically switched to POST method due to request body data")
    
    # Validate method
    valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
    if method not in valid_methods:
        print(f"Warning: Unsupported HTTP method: {method}. Using GET instead.")
        method = "GET"
    
    # Check for streaming response
    stream = args.stream or args.save  # Always stream if saving to file
    kwargs["stream"] = stream
    
    try:
        # Print request info in verbose mode
        if args.verbose:
            print(f"Sending {method} request to {validated_url}")
            print(f"Headers: {json.dumps(headers, indent=2)}")
            if data and not is_binary and not kwargs.get("files"):
                print(f"Data: {data}")
            print(f"Timeout: {args.timeout}s, Verify SSL: {verify}, Allow Redirects: {allow_redirects}")
            if auth:
                print(f"Using authentication: {args.auth_type}")
            if cookies:
                print(f"Cookies: {cookies}")
            if params:
                print(f"Query Parameters: {params}")
            print("\nWaiting for response...\n")
            start_time = time.time()
        
        # Send the request
        response = session.request(method=method, **kwargs)
        
        # Calculate response time in verbose mode
        if args.verbose:
            end_time = time.time()
            print(f"Request completed in {end_time - start_time:.2f} seconds")
        
        # Process the response
        print(f"Status Code: {response.status_code} {response.reason}")
        
        # Print headers
        print("Response Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")
        
        # Handle streaming response
        if stream:
            if args.save:
                content_type = response.headers.get('Content-Type', '')
                is_binary_response = not content_type.startswith(('text/', 'application/json', 'application/xml'))
                
                # Use appropriate mode based on content type
                with open(args.save, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"\nResponse saved to {args.save}")
            else:
                # For non-binary streaming without saving
                for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                    if chunk:
                        sys.stdout.write(chunk)
        else:
            # Non-streaming response handling
            try:
                if args.save:
                    # Determine if binary based on content type
                    content_type = response.headers.get('Content-Type', '')
                    is_binary_response = not content_type.startswith(('text/', 'application/json', 'application/xml'))
                    save_response(response.content if is_binary_response else response.text, 
                                 args.save, binary=is_binary_response)
                else:
                    print("\nResponse Body:")
                    # Format and print the response
                    print(format_response(response, args))
                    
            except UnicodeDecodeError:
                print("Warning: Unable to decode response with specified encoding. Response might be binary data.")
                if args.save:
                    save_response(response.content, args.save, binary=True)
                else:
                    print("Binary response received. Use --save option to save the response to a file.")
        
    except requests.exceptions.Timeout:
        print(f"Error: Request timed out after {args.timeout} seconds")
        sys.exit(1)
    except requests.exceptions.TooManyRedirects:
        print(f"Error: Too many redirects")
        sys.exit(1)
    except requests.exceptions.SSLError:
        print("Error: SSL Certificate verification failed. Use --no-verify to ignore SSL certificate verification")
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"Error: Connection failed - {str(e)}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error sending request: {str(e)}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)


def main():
    """Main function to run the gepo tool."""
    try:
        # Initialize mimetype detection
        mimetypes.init()
        
        # Parse arguments
        args = parse_arguments()
        
        # Send request
        send_request(args)
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()