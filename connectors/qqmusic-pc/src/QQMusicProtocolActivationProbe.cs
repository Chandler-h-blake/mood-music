using System;
using System.Runtime.InteropServices;

namespace MoodMusic.QQMusicPc
{
    internal static class QQMusicProtocolActivationProbe
    {
        private static readonly Guid ClassId = new Guid("37af9b7d-85e7-4a76-821e-a309ff8f4399");
        private static readonly Guid ClassFactoryId = new Guid("00000001-0000-0000-c000-000000000046");
        private static readonly Guid TencentProtocolId = new Guid("b5742eec-becd-4049-81bd-3c38032117aa");

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int DllGetClassObjectDelegate(
            ref Guid classId,
            ref Guid interfaceId,
            out IntPtr result
        );

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        private delegate int CreateInstanceDelegate(
            IntPtr self,
            IntPtr outer,
            ref Guid interfaceId,
            out IntPtr result
        );

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
                Console.Error.WriteLine("Expected the QQMusic_Protocol.dll path.");
                return 2;
            }

            IntPtr module = IntPtr.Zero;
            IntPtr factory = IntPtr.Zero;
            IntPtr protocol = IntPtr.Zero;
            bool comInitialized = false;
            try
            {
                int initializeResult = CoInitializeEx(IntPtr.Zero, 2);
                comInitialized = initializeResult >= 0;
                if (!comInitialized)
                {
                    throw new COMException("CoInitializeEx failed.", initializeResult);
                }

                module = LoadLibraryEx(arguments[0], IntPtr.Zero, 8);
                if (module == IntPtr.Zero)
                {
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
                }
                IntPtr export = GetProcAddress(module, "DllGetClassObject");
                if (export == IntPtr.Zero)
                {
                    throw new MissingMethodException("DllGetClassObject is not exported.");
                }

                var getClassObject = (DllGetClassObjectDelegate)Marshal.GetDelegateForFunctionPointer(
                    export,
                    typeof(DllGetClassObjectDelegate)
                );
                Guid classId = ClassId;
                Guid factoryId = ClassFactoryId;
                int factoryResult = getClassObject(ref classId, ref factoryId, out factory);
                if (factoryResult < 0 || factory == IntPtr.Zero)
                {
                    throw new COMException("DllGetClassObject failed.", factoryResult);
                }

                IntPtr factoryVtable = Marshal.ReadIntPtr(factory);
                IntPtr createAddress = Marshal.ReadIntPtr(factoryVtable, 3 * IntPtr.Size);
                var createInstance = (CreateInstanceDelegate)Marshal.GetDelegateForFunctionPointer(
                    createAddress,
                    typeof(CreateInstanceDelegate)
                );
                Guid protocolId = TencentProtocolId;
                int createResult = createInstance(
                    factory,
                    IntPtr.Zero,
                    ref protocolId,
                    out protocol
                );
                if (createResult < 0 || protocol == IntPtr.Zero)
                {
                    throw new COMException("IClassFactory.CreateInstance failed.", createResult);
                }

                Console.WriteLine(
                    "{\"activated\":true,\"classId\":\"" + ClassId
                    + "\",\"interfaceId\":\"" + TencentProtocolId + "\"}"
                );
                return 0;
            }
            catch (Exception error)
            {
                int code = error is COMException ? ((COMException)error).ErrorCode : Marshal.GetHRForException(error);
                Console.Error.WriteLine(
                    error.GetType().Name + " 0x" + code.ToString("X8") + ": " + error.Message
                );
                return 1;
            }
            finally
            {
                if (protocol != IntPtr.Zero) Marshal.Release(protocol);
                if (factory != IntPtr.Zero) Marshal.Release(factory);
                if (module != IntPtr.Zero) FreeLibrary(module);
                if (comInitialized) CoUninitialize();
            }
        }
    }
}
