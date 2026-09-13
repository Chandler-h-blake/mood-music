using System;
using System.Collections;
using System.Runtime.InteropServices;

namespace MoodMusic.QQMusicPc
{
    internal static class QQMusicComProbe
    {
        [STAThread]
        private static int Main()
        {
            object player = null;
            try
            {
                Type playerType = Type.GetTypeFromProgID("QQMusicSvr.QQMusicPlayer", true);
                player = Activator.CreateInstance(playerType);
                dynamic automation = player;

                uint currentSongId = 0;
                uint itemCount = 0;
                object itemIds = null;
                string currentSongError = null;
                string itemCountError = null;
                string itemIdsError = null;

                try
                {
                    automation.GetCurrentPlaySongID(out currentSongId);
                }
                catch (Exception error)
                {
                    currentSongError = ErrorName(error);
                }
                try
                {
                    automation.GetPlayItemCount(out itemCount);
                }
                catch (Exception error)
                {
                    itemCountError = ErrorName(error);
                }
                try
                {
                    automation.EnumPlayItemIDs(out itemIds);
                }
                catch (Exception error)
                {
                    itemIdsError = ErrorName(error);
                }

                int enumeratedCount = CountValues(itemIds);
                Console.WriteLine(
                    "{\"activated\":true,\"currentSongId\":" + currentSongId
                    + ",\"itemCount\":" + itemCount
                    + ",\"enumeratedCount\":" + enumeratedCount
                    + ",\"currentSongQuery\":\"" + QueryStatus(currentSongError) + "\""
                    + ",\"itemCountQuery\":\"" + QueryStatus(itemCountError) + "\""
                    + ",\"itemIdsQuery\":\"" + QueryStatus(itemIdsError) + "\"}"
                );
                return currentSongError == null && itemCountError == null && itemIdsError == null
                    ? 0
                    : 2;
            }
            catch (Exception error)
            {
                Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
                return 1;
            }
            finally
            {
                if (player != null && Marshal.IsComObject(player))
                {
                    Marshal.FinalReleaseComObject(player);
                }
            }
        }

        private static int CountValues(object value)
        {
            if (value == null)
            {
                return 0;
            }
            Array array = value as Array;
            if (array != null)
            {
                return array.Length;
            }
            ICollection collection = value as ICollection;
            return collection != null ? collection.Count : 1;
        }

        private static string ErrorName(Exception error)
        {
            return error.GetType().Name;
        }

        private static string QueryStatus(string errorName)
        {
            return errorName ?? "ok";
        }
    }
}
