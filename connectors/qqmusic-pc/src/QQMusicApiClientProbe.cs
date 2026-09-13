using System;
using System.Runtime.InteropServices;

namespace MoodMusic.QQMusicPc
{
    internal static class QQMusicApiClientProbe
    {
        private static readonly Guid ClassId = new Guid("05cb0b5a-57fa-4067-b405-e1acca3035df");
        private static readonly Guid ClassFactoryId = new Guid("00000001-0000-0000-c000-000000000046");
        private static readonly Guid ClientId = new Guid("eebc7e3f-b437-42a7-9c16-6978660a2e5c");

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int DllGetClassObjectDelegate(ref Guid classId, ref Guid interfaceId, out IntPtr result);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int CreateInstanceDelegate(IntPtr self, IntPtr outer, ref Guid interfaceId, out IntPtr result);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int GetVersionDelegate(IntPtr self, out uint version);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr module, string name);

        [DllImport("kernel32.dll")]
        private static extern bool FreeLibrary(IntPtr module);

        [DllImport("ole32.dll")]
        private static extern int CoInitializeEx(IntPtr reserved, uint concurrencyModel);

        [DllImport("ole32.dll")]
        private static extern void CoUninitialize();

        [STAThread]
        private static int Main(string[] arguments)
        {
            if (arguments.Length != 1)
            {
                Console.Error.WriteLine("Expected the QQMusicApi.dll path.");
                return 2;
            }
            IntPtr module = IntPtr.Zero;
            IntPtr factory = IntPtr.Zero;
            IntPtr client = IntPtr.Zero;
            bool comInitialized = false;
            try
            {
                int initializeResult = CoInitializeEx(IntPtr.Zero, 2);
                comInitialized = initializeResult >= 0;
                if (!comInitialized) throw new COMException("CoInitializeEx failed.", initializeResult);

                module = LoadLibraryEx(arguments[0], IntPtr.Zero, 8);
                if (module == IntPtr.Zero)
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                IntPtr export = GetProcAddress(module, "DllGetClassObject");
                if (export == IntPtr.Zero) throw new MissingMethodException("DllGetClassObject is not exported.");
                var getClassObject = (DllGetClassObjectDelegate)Marshal.GetDelegateForFunctionPointer(
                    export, typeof(DllGetClassObjectDelegate)
                );
                Guid classId = ClassId;
                Guid factoryId = ClassFactoryId;
                int result = getClassObject(ref classId, ref factoryId, out factory);
                if (result < 0 || factory == IntPtr.Zero)
                    throw new COMException("DllGetClassObject failed.", result);

                IntPtr vtable = Marshal.ReadIntPtr(factory);
                var createInstance = (CreateInstanceDelegate)Marshal.GetDelegateForFunctionPointer(
                    Marshal.ReadIntPtr(vtable, 3 * IntPtr.Size), typeof(CreateInstanceDelegate)
                );
                Guid clientId = ClientId;
                result = createInstance(factory, IntPtr.Zero, ref clientId, out client);
                if (result < 0 || client == IntPtr.Zero)
                    throw new COMException("IClassFactory.CreateInstance failed.", result);

                IntPtr clientVtable = Marshal.ReadIntPtr(client);
                var getVersion = (GetVersionDelegate)Marshal.GetDelegateForFunctionPointer(
                    Marshal.ReadIntPtr(clientVtable, 18 * IntPtr.Size),
                    typeof(GetVersionDelegate)
                );
                uint version;
                result = getVersion(client, out version);
                if (result < 0) throw new COMException("IQMApiCli.GetVersion failed.", result);
                Console.WriteLine(
                    "{\"activated\":true,\"version\":" + version + "}"
                );
                return 0;
            }
            catch (Exception error)
            {
                int code = error is COMException ? ((COMException)error).ErrorCode : Marshal.GetHRForException(error);
                Console.Error.WriteLine(error.GetType().Name + " 0x" + code.ToString("X8") + ": " + error.Message);
                return 1;
            }
            finally
            {
                if (client != IntPtr.Zero) Marshal.Release(client);
                if (factory != IntPtr.Zero) Marshal.Release(factory);
                if (module != IntPtr.Zero) FreeLibrary(module);
                if (comInitialized) CoUninitialize();
            }
        }

    }
}
